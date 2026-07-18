Final Implementation Plan — Redesign Annotation, Signal, and Loading API
Problem Statement: Restructure two core data models in the edfplus library: (1) simplify Annotation to hold a single text: str instead of texts: list[str], emitting multiple Annotation instances for multi-text TAL blocks; (2) merge SignalHeader into Signal as a dataclass with a weakref back-reference to EDFFile, index/byte-range awareness, and a powerful load() method that supports flexible cropping by sample index, seconds, datetime, or timedelta. Remove read_signals() in favor of per-signal lazy/eager loading. Add load_with_timestamps() companion.

Requirements:

Annotation.text: str replaces Annotation.texts: list[str]; one Annotation per text string
SignalHeader class removed entirely (deleted); fields inlined into Signal dataclass
Signal holds weakref.ref[EDFFile], its own index, and byte-range info
Signal.samples property auto-loads full data on first access (cached)
Signal.load(start, stop, onset, duration) — type-overloaded cropping: int=index, float=seconds, datetime=absolute, timedelta=offset. Returns ndarray
Signal.load_with_timestamps(...) — same params plus time_format: Literal["seconds","datetime"], returns (samples, timestamps) tuple
EDFFile.read_signals() removed
edf.signals always contains all wired Signal instances
read_edf(..., eager_load_samples=True) eagerly loads all samples
SignalHeader removed from public exports
Signal.load() parameter resolution:

Python type	Interpretation
int	Sample index (negative = from end)
float	Seconds from recording start
datetime.datetime	Absolute time → seconds via (dt - start_datetime).total_seconds()
datetime.timedelta	Offset from start → .total_seconds()
onset is an alias for start (same type resolution)
duration is float (seconds) or timedelta; combined with start to compute stop
Conflicts (start + onset, or stop + duration) raise ValueError
Task Breakdown:

Task 1: Redesign Annotation dataclass and update TAL parser

Objective: Change Annotation from texts: list[str] to text: str and update _tal.py to emit one Annotation per text string.

Implementation guidance:

In _models.py: replace texts: list[str] = field(default_factory=list) with text: str. Keep frozen=True.
In _tal.py / parse_tals(): after _parse_tal_block returns (onset, duration, texts), iterate texts and append Annotation(onset=onset, duration=duration, text=t) for each string. If texts is empty after a non-timekeeping TAL, skip it (no annotation with empty text).
_parse_tal_block internal return type stays tuple[float, float | None, list[str]] — flattening happens in parse_tals()
Test requirements:

Update test_tal_parsing_fix.py: assertions at _parse_tal_block level are unchanged (they test the internal helper). Add tests for parse_tals() verifying multi-text TAL blocks produce multiple Annotation objects (e.g., +1.5\x14Event A\x14Event B\x14\x00 → 2 annotations with text="Event A" and text="Event B", same onset/duration)
Update test_integration.py to access ann.text instead of ann.texts
Demo: parse_tals() returns separate Annotation instances per text string. annotation.text works. Tests pass.

Task 2: Create Signal dataclass, remove SignalHeader

Objective: Delete SignalHeader entirely. Make Signal a @dataclass with all header fields as direct fields plus private fields for lazy loading.

Implementation guidance:

In _models.py: remove SignalHeader class. Define:
python

@dataclass
class Signal:
    label: str
    transducer_type: str
    physical_dimension: str
    physical_min: float
    physical_max: float
    digital_min: int
    digital_max: int
    prefiltering: str
    samples_per_record: int
    sample_rate: float
    is_annotation: bool
    index: int
    _edf_file: weakref.ref[EDFFile] | None = field(default=None, repr=False)
    _byte_offset_in_record: int = field(default=0, repr=False)
    _bytes_per_record: int = field(default=0, repr=False)
    _physical: bool = field(default=True, repr=False)
    _dtype: numpy.dtype | None = field(default=None, repr=False)
    _samples: numpy.ndarray | None = field(default=None, init=False, repr=False)
Keep samples as a @property on the class (dataclass + property pattern). The property calls _ensure_loaded() on first access.
Keep timestamps(), datetimes(), physical_samples(), digital_samples() methods.
For datetimes(): access start_datetime via the weakref (self._edf_file().header.start_datetime).
Test requirements:

Unit test: construct Signal with all fields, verify attribute access
Verify dataclasses.is_dataclass(Signal) is True
Verify Signal is not frozen (needs mutable _samples)
Demo: Signal is instantiable as a dataclass. SignalHeader no longer exists.

Task 3: Update _header.py to produce Signal objects directly

Objective: Change parse_signal_headers() to return list[Signal] instead of list[SignalHeader].

Implementation guidance:

parse_signal_headers() constructs Signal(label=..., ..., index=i, _edf_file=None, _byte_offset_in_record=0, _bytes_per_record=0) for each signal
Return type annotation: list[Signal]
Update imports: from edfplus._models import Signal (remove SignalHeader)
Test requirements:

Existing test_header.py tests pass (they test field values, not the class type directly — but update any type assertions if present)
Quick test that parse_signal_headers returns Signal instances
Demo: parse_signal_headers() returns Signal objects. Header tests pass.

Task 4: Update _scaler.py to accept Signal

Objective: Replace all SignalHeader references in _scaler.py with Signal.

Implementation guidance:

Change type annotations: sh: SignalHeader → signal: Signal (or keep param name sh for minimal diff — either works since attribute names are identical)
Remove from edfplus._models import SignalHeader, add from edfplus._models import Signal
Function bodies unchanged (same attribute names)
Test requirements:

test_scaler_edffloat.py — update any SignalHeader(...) construction to use Signal(...) with all required fields
Verify scaling still works
Demo: scale_signal() accepts Signal. Scaler tests pass.

Task 5: Implement Signal.load() with cropping and Signal.load_with_timestamps()

Objective: Implement the powerful load() method with type-overloaded start/stop/onset/duration parameters, and the companion load_with_timestamps().

Implementation guidance:

Private helper _resolve_bounds(self, start, stop, onset, duration) -> tuple[int, int]:
Validate mutual exclusivity: start and onset can't both be set; stop and duration can't both be set
Merge: effective_start = start if start is not None else onset; effective_stop uses stop or computes from duration
Type dispatch per value:
None → default (0 for start, total_samples for stop)
int → direct index; negative wraps via total_samples + idx
float → int(value * self.sample_rate)
datetime.datetime → int((dt - start_datetime).total_seconds() * self.sample_rate)
datetime.timedelta → int(td.total_seconds() * self.sample_rate)
For duration: compute seconds (float directly, or td.total_seconds()), then stop_idx = start_idx + int(dur_seconds * self.sample_rate)
Clamp to [0, total_samples]
_ensure_loaded(self): if _samples is None, call _read_own_samples(), apply scaling if _physical, store in _samples
_read_own_samples(self) -> numpy.ndarray: uses weakref to get EDFFile, reads from _f using byte offsets, handles EDF+D gaps via edf._record_onsets
load(self, start=None, stop=None, onset=None, duration=None) -> ndarray:
Calls _ensure_loaded()
Resolves bounds
Returns self._samples[start_idx:stop_idx]
load_with_timestamps(self, start=None, stop=None, onset=None, duration=None, time_format="seconds") -> tuple[ndarray, ndarray]:
Calls load(...) to get samples slice
Computes timestamps for slice indices:
"seconds" → arange(start_idx, stop_idx, dtype=float64) / sample_rate
"datetime" → start_datetime + timedelta per sample as datetime64[us]
Returns (samples, timestamps)
samples property: calls _ensure_loaded(), returns _samples
Test requirements:

load() with no args returns full samples (same as .samples)
load(start=10, stop=20) returns 10 samples (int indexing)
load(start=1.0, stop=2.0) for 256 Hz signal returns 256 samples
load(onset=1.0, duration=0.5) returns 128 samples at 256 Hz
load(start=datetime(...), stop=datetime(...)) resolves correctly
load(start=timedelta(seconds=1)) resolves correctly
ValueError when both start and onset specified
ValueError when both stop and duration specified
Negative int indexing: load(start=-100) returns last 100 samples
load_with_timestamps(time_format="seconds") returns (samples, float64 timestamps)
load_with_timestamps(time_format="datetime") returns (samples, datetime64 timestamps)
Auto-load on .samples property access works and caches
Demo: signal.load(start=1.0, stop=5.0) returns cropped samples. signal.load_with_timestamps(onset=0.5, duration=2.0, time_format="seconds") returns (samples, timestamps).

Task 6: Rewire EDFFile and read_edf() — remove read_signals(), add eager_load_samples

Objective: Remove read_signals() from EDFFile. Wire Signal instances with weakrefs and byte offsets in read_edf(). Add eager_load_samples kwarg.

Implementation guidance:

In reader.py / read_edf():
After calling parse_signal_headers() (returns list[Signal]), compute byte layout:
python

bytes_per_signal = [sig.samples_per_record * 2 for sig in all_signals]
total_bytes_per_record = sum(bytes_per_signal)
for i, sig in enumerate(all_signals):
    sig._byte_offset_in_record = sum(bytes_per_signal[:i])
    sig._bytes_per_record = total_bytes_per_record
Construct EDFFile, then wire each non-annotation Signal:
python

sig._edf_file = weakref.ref(edf_file)
sig._physical = physical
sig._dtype = resolved_dtype
For EDF+D: pre-parse time-keeping onsets from all records, store as edf._record_onsets: list[float]
Add eager_load_samples: bool = False param. When True, call sig.load() on each non-annotation signal after wiring.
edf.signals = list of non-annotation Signal instances
In _models.py / EDFFile:
Remove read_signals() method
Remove _signal_headers field and _physical/_dtype fields (those live on Signal now)
Add _record_onsets: list[float] field
Add _all_signals: list[Signal] (includes annotation signals, needed for byte offset calculation during per-signal reading)
Keep __getitem__, context manager, close()
Update __init__.py: remove SignalHeader from __all__
Test requirements:

Rewrite test_read_signals.py → use edf.signals[0].samples / .load() pattern
Test eager_load_samples=True makes .samples accessible without disk I/O
Test edf.signals populated immediately after read_edf()
Test edf["EEG A"].load(start=0, stop=10) works
Update test_reader.py — remove read_signals references, add eager_load_samples tests
Update test_integration.py for new API
Demo: read_edf("file.edf") → edf.signals[0].samples lazy-loads. read_edf("file.edf", eager_load_samples=True) loads upfront. edf.read_signals no longer exists.

Task 7: Implement per-signal disk reading with EDF+D support

Objective: Implement Signal._read_own_samples() that reads a single signal's data across all records, with EDF+D gap insertion.

Implementation guidance:

New function (can live in _records.py or as a method on Signal):
python

def read_single_signal(f, header, signal, record_onsets) -> numpy.ndarray:
For each record r in range(num_records):
Seek to header.header_bytes + r * signal._bytes_per_record + signal._byte_offset_in_record
Read signal.samples_per_record * 2 bytes → int16 array
For EDF+D with record_onsets: insert NaN gaps between records (same logic as current _insert_gaps but for one signal)
Return concatenated array
Signal._read_own_samples() calls this, then applies scaling via scale_signal() if _physical
The old read_signal_data() batch function can be removed or deprecated (it's no longer called)
Test requirements:

Per-signal reading produces identical results to the old batch function for the same signal
EDF+D gap insertion works correctly for a single signal
Reading after file handle closed raises appropriate error
Demo: Single-signal lazy load from disk works. EDF+D gaps inserted correctly.

Task 8: Final cleanup — tests, exports, formatting, type-checking

Objective: Remove all SignalHeader references, update all tests and docs, ensure clean CI.

Implementation guidance:

Remove SignalHeader from all imports everywhere
Update conftest.py if it references SignalHeader
Grep .texts → .text across all files
Update all docstrings on EDFFile, Signal, Annotation
__init__.py __all__ = ["read_edf", "EDFFile", "EDFHeader", "Signal", "Annotation"]
Run: uv run ruff check --fix && uv run ruff format && uv run pytest tests/ && uv run ty check
Test requirements:

uv run pytest tests/ all green
uv run ruff check clean
uv run ty check passes
Demo: Full test suite passes. Linter and type-checker clean. Public API: read_edf, EDFFile, EDFHeader, Signal, Annotation.

The plan is approved. To execute it, switch out of Plan mode (e.g. select Default or Autonomous mode) and the tasks can be implemented sequentially.