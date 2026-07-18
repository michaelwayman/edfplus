# Implementation Plan: EDF File Reader

## Overview

Implement a complete EDF/EDF+ binary file reader for the `edfplus` Python library.
The pipeline runs: header parsing → TAL parsing → selective record reading → scaling →
public API surface. Implementation language: **Python** (≥ 3.14 with NumPy ≥ 2.5.1).

## Tasks

- [x] 1. Project setup and test infrastructure
  - Add `hypothesis>=6.0` to `[dependency-groups.dev]` in `pyproject.toml`
  - Create `tests/conftest.py` with helper functions:
    - `make_global_header(**fields) -> bytes` — builds a 256-byte global header from keyword args with sensible defaults
    - `make_signal_headers(signals: list[dict]) -> bytes` — builds the `ns × 256`-byte per-signal block
    - `make_data_record(samples: list[list[int]]) -> bytes` — packs int16 samples in EDF interleaved order
    - `make_tal_bytes(annotations: list[tuple]) -> bytes` — encodes TAL byte sequences
  - _Requirements: 10.1_


- [x] 2. Implement data models (`_models.py`)
  - [x] 2.1 Implement `EDFHeader`, `SignalHeader`, and `Annotation` dataclasses
    - All fields as specified in the design's Data Models section
    - `EDFHeader` includes `_raw_global: bytes` and `_raw_signals: bytes` for round-trip fidelity
    - `SignalHeader` includes `is_annotation: bool`
    - `Annotation` with `onset: float`, `duration: float | None`, `texts: list[str]`
    - All dataclasses frozen (`frozen=True`)
    - Fully typed with Google-style docstrings
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.7, 3.1, 3.2, 7.2_

  - [x] 2.2 Implement `Signal` class
    - Constructor accepts `SignalHeader`, `EDFHeader`, and optional `numpy.ndarray`
    - All header pass-through read-only properties: `label`, `transducer_type`, `physical_dimension`, `physical_min`, `physical_max`, `digital_min`, `digital_max`, `prefiltering`, `samples_per_record`, `sample_rate`
    - `samples` property raises `RuntimeError` when sample data is not loaded
    - `physical_samples(dtype=None)` and `digital_samples()` methods
    - `timestamps()` method: `numpy.arange(n) / sample_rate`, NaN at gap positions
    - `datetimes()` method: `origin + timedelta(seconds=ts[i])`, NaT at gap positions
    - _Requirements: 3.7, 4.3, 4.7, 4.10, 4.11, 10.7, 10.8, 10.9, 10.15, 10.16_

  - [x] 2.3 Implement `EDFFile` class
    - Constructor stores header, signal stubs, annotations, file handle, `_physical`, `_dtype`
    - `header`, `signals`, `annotations` read-only properties
    - `__getitem__` supporting both `str` (label → `KeyError` if missing) and `int` (index → `IndexError` if out of range)
    - Stub `read_signals()` method signature (implementation wired in task 7)
    - Context manager `__enter__`/`__exit__` and `close()` methods
    - _Requirements: 4.5, 4.6, 10.4, 10.5, 10.6_

  - [ ]* 2.4 Write unit tests for `_models.py`
    - Test `Signal` header property forwarding for all 10 properties
    - Test `Signal.samples` raises before loading, returns array after loading
    - Test `EDFFile.__getitem__` raises `KeyError` for unknown label, `IndexError` for out-of-range int
    - Test context manager closes file handle on `__exit__`
    - _Requirements: 3.7, 4.5, 4.6, 10.4, 10.6_


- [x] 3. Implement global header parsing (`_header.py` — global portion)
  - [x] 3.1 Implement `parse_global_header(data: bytes, file_size: int, tzinfo: datetime.tzinfo | None) -> EDFHeader`
    - Read exactly 256 bytes; raise `ValueError("truncated header")` if shorter
    - Decode all fields: version (8), patient id (80), recording id (80), start date (8), start time (8), header bytes (8), reserved (44), num_records (8), record_duration (8), ns (4)
    - Raise `ValueError` (with field name + raw value) for any field that cannot be parsed as its expected numeric type
    - Validate version == `"0       "` (raise `ValueError` with found value if not)
    - Detect variant from reserved field: `"EDF+C"`, `"EDF+D"`, blank → `"EDF"`, other non-blank → `ValueError` with raw value
    - Apply two-digit year rule: `yy >= 85 → 19xx`, `yy < 85 → 20xx`
    - Attach `tzinfo` to `start_time` and `start_datetime` via `.replace(tzinfo=tzinfo)`; `start_date` stays plain
    - Store `_raw_global = data[:256]` for round-trip fidelity
    - _Requirements: 1.3, 1.4, 1.5, 1.7, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10_

  - [x] 3.2 Parse EDF+ patient and recording subfields inside `parse_global_header`
    - For `EDF+C`/`EDF+D`: split patient id on space into 4 positional subfields (hospital code, sex, birthdate, patient name)
    - Map `"X"` → `None` for any subfield; replace underscores with spaces in non-`None` values
    - Parse birthdate with `datetime.strptime(val, "%d-%b-%Y")`; raise `ValueError("local patient identification birthdate", raw)` on failure
    - Split recording id into 4 subfields (startdate, investigation code, investigator code, equipment code)
    - Parse recording startdate with same format; raise `ValueError("local recording identification startdate", raw)` on failure
    - For plain `EDF`: set all EDF+ subfields to `None`
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8_

  - [ ]* 3.3 Write unit tests for `parse_global_header`
    - Happy path: valid 256-byte header parses all fields correctly
    - Version validation: non-`"0       "` raises `ValueError`
    - Variant detection: EDF+C, EDF+D, blank, unrecognized non-blank reserved
    - Two-digit year: `yy=84 → 2084`, `yy=85 → 1985`, `yy=00 → 2000`, `yy=99 → 1999`
    - `num_records == -1` inference
    - `tzinfo` attached correctly; `tzinfo=None` gives naive objects
    - EDF+ subfield parsing: `"X"` → `None`, underscore → space, birthdate format
    - Error cases: non-numeric `ns`, non-numeric `record_duration`, truncated buffer
    - _Requirements: 1.3, 1.7, 2.2, 2.3, 2.4, 2.5, 2.7, 2.8, 2.9, 2.10, 6.1–6.8_


- [x] 4. Implement per-signal header parsing (`_header.py` — signal portion)
  - [x] 4.1 Implement `parse_signal_headers(data: bytes, ns: int, record_duration: float) -> list[SignalHeader]`
    - Stride through buffer by field: labels (16 each), transducer (80), physical dim (8), physical min (8), physical max (8), digital min (8), digital max (8), prefiltering (80), samples per record (8), reserved (32)
    - Strip all string fields; parse numeric fields as float/int
    - Raise `ValueError(signal_index, field_name, raw_value)` for any unparseable numeric field
    - Compute `sample_rate = samples_per_record / record_duration`; set to `0` when `record_duration == 0`
    - Set `is_annotation = True` when stripped label == `"EDF Annotations"`
    - Store `_raw_signals` bytes reference for round-trip fidelity (passed back to caller or stored on EDFHeader)
    - Validate header byte count `== 256 + ns * 256` (raise `ValueError("malformed header")` if not)
    - _Requirements: 1.4, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

  - [ ]* 4.2 Write unit tests for `parse_signal_headers`
    - Happy path: known ns=3 buffer parses all 3 signal headers correctly
    - `"EDF Annotations"` signal gets `is_annotation=True`
    - `record_duration=0` gives `sample_rate=0` (no ZeroDivisionError)
    - Stripped whitespace on label, transducer, physical_dimension, prefiltering
    - Non-numeric physical_min raises `ValueError` with signal index and field name
    - Malformed header byte count raises `ValueError("malformed header")`
    - _Requirements: 3.1–3.6_

  - [ ]* 4.3 Write property tests for `_header.py`
    - **Property 1: Global header round-trip** — parse then format `EDFHeader` back to 256 bytes, assert byte-identical
    - **Property 2: Per-signal header round-trip** — parse then format `ns × 256` bytes, assert byte-identical
    - **Property 6: Invalid reserved field rejected** — any non-blank non-EDF+C/D reserved value raises `ValueError`
    - **Property 7: Two-digit year century rule** — `yy ∈ [0,99]`: year is `1900+yy` when `≥85`, else `2000+yy`
    - **Property 8: String fields stripped** — any label/transducer/dim/prefiltering with arbitrary leading/trailing spaces has no leading/trailing spaces after parsing
    - **Property 9: Sample rate derivation** — `sample_rate == samples_per_record / record_duration` for all valid inputs
    - **Property 16: "X" subfield → None** — any positional EDF+ subfield value `"X"` maps to `None`
    - **Property 17: Underscore → space replacement** — any non-X EDF+ subfield with underscores has them replaced by spaces
    - **Property 21: Invalid numeric fields raise ValueError** — non-numeric bytes in `ns`, `num_records`, `record_duration` raise `ValueError` with field name
    - _Requirements: 9.1, 9.2, 9.3, 2.5, 2.7, 3.4, 3.2, 6.2, 6.8, 1.7, 2.8_


- [x] 5. Implement TAL parsing (`_tal.py`)
  - [x] 5.1 Implement `parse_tals(data: bytes, record_index: int) -> tuple[float | None, list[Annotation]]`
    - Scan byte sequence for TAL boundaries (`0x00` terminates; unused bytes are `0x00`)
    - Within each TAL: split on `0x15` to separate onset+duration token from text tokens
    - Split text section on `0x14`; discard empty strings
    - Parse onset from ASCII decimal; validate range `[-999999.999, +999999.999]`; raise `ValueError(record_index, raw_onset)` if invalid or out of range
    - Parse optional duration from the onset token if a `0x15` separator is present after the onset
    - Raise `ValueError(record_index, byte_shortfall)` if annotation signal data is shorter than declared sample count
    - First TAL in each record has empty text: extract its onset as `timekeeping_onset` and exclude from returned list
    - Return `(timekeeping_onset, annotations)` where annotations are all non-timekeeping entries with non-empty text lists
    - _Requirements: 7.1, 7.2, 7.3, 7.5, 7.6, 7.7_

  - [ ]* 5.2 Write unit tests for `parse_tals`
    - Happy path: known TAL bytes with two annotations → correct onset/duration/texts
    - Time-keeping TAL extracted as onset and not in returned list
    - Empty text segments omitted from `Annotation.texts`
    - Onset out of range raises `ValueError` with record index
    - Non-numeric onset bytes raise `ValueError`
    - Multiple annotations across records maintain order
    - _Requirements: 7.1–7.7_

  - [ ]* 5.3 Write property tests for `_tal.py`
    - **Property 18: TAL onset ordering** — annotations list from any valid multi-TAL input is in non-decreasing onset order
    - **Property 19: TAL onset/duration round-trip** — encode a TAL byte sequence then parse it, `Annotation.onset` and `duration` match original values within float precision
    - **Property 20: Empty texts excluded** — any TAL with empty text segments (adjacent `0x14 0x14`) produces `Annotation.texts` with no empty strings
    - _Requirements: 7.4, 7.2, 7.3_


- [x] 6. Implement signal scaling (`_scaler.py`)
  - [x] 6.1 Implement linear `scale_signal` path
    - `scale_signal(digital: numpy.ndarray, sh: SignalHeader, dtype: numpy.dtype | None) -> numpy.ndarray`
    - Compute `gain = (physical_max - physical_min) / (digital_max - digital_min)`
    - Apply: `physical = physical_min + (digital - digital_min) * gain`
    - Guard: when `digital_max == digital_min`, return array filled with `physical_min` (no division)
    - NaN passthrough: preserve NaN values from EDF+D gap insertion in output
    - Cast to `dtype` if provided; default output dtype is `float64`
    - _Requirements: 4.2, 4.3, 4.4, 4.8_

  - [x] 6.2 Implement edffloat `scale_signal` path
    - Detect edffloat: `physical_dimension == "Filtered"` AND `physical_max == 32767` AND `digital_max == 32767`
    - Parse `Ymin` and `a` from prefiltering field using regex `r"sign\*LN\[sign\*\((.{8})\)/\((.{8})\)\]/\((.{8})\)"`
    - Raise `ValueError(signal_label)` if regex fails, or `Ymin <= 0`, or `a <= 0`
    - Apply three-branch transform element-wise: `N>0 → Ymin*exp(a*N)`, `N==0 → 0.0`, `N<0 → -Ymin*exp(-a*N)`
    - Preserve NaN positions; cast to `dtype` if provided
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [ ]* 6.3 Write unit tests for `_scaler.py`
    - Linear: known calibration params and digital values → expected physical values
    - Linear: `digital_max == digital_min` returns all-`physical_min` array without error
    - Linear: `dtype=numpy.float32` casts output correctly
    - edffloat: known `Ymin`, `a`, `N` values produce correct `Y`
    - edffloat: `N=0` → `Y=0.0`, `N<0` → negative result
    - edffloat: invalid prefiltering string raises `ValueError` with signal label
    - edffloat: `Ymin <= 0` or `a <= 0` raises `ValueError`
    - NaN passthrough: NaN in input → NaN in output for both paths
    - _Requirements: 4.2, 4.3, 4.4, 4.8, 5.1–5.6_

  - [ ]* 6.4 Write property tests for `_scaler.py`
    - **Property 3: Linear scaling invertibility** — scale then invert-scale recovers original `int16` values to within ±1 LSB
    - **Property 4: edffloat scaling invertibility** — edffloat digital→physical→digital round-trip recovers `N` exactly
    - _Requirements: 4.2, 4.3, 5.3, 5.4, 5.5_


- [x] 7. Implement data record reading (`_records.py`)
  - [x] 7.1 Implement `read_signal_data` — core selective loading
    - `read_signal_data(f: BinaryIO, header: EDFHeader, signal_headers: list[SignalHeader], indices: list[int]) -> dict[int, numpy.ndarray]`
    - Seek to `header.header_bytes` before reading
    - For each record, iterate signals in file order: `f.read(n_bytes)` for requested indices; `f.seek(n_bytes, 1)` for non-requested
    - Infer record count when `header.num_records == -1`: `(file_size - header_bytes) // bytes_per_record`
    - Accumulate `int16` arrays per requested index; return as `dict[int, ndarray]`
    - For EDF+C: annotate channel is skipped (seek-only) but still advances file position correctly
    - _Requirements: 4.1, 8.3, 10.18, 10.23_

  - [x] 7.2 Implement EDF+D gap insertion in `read_signal_data`
    - After reading each record, call `parse_tals` on the annotations signal bytes to get `timekeeping_onset`
    - Raise `ValueError(record_index)` if EDF+D record has no time-keeping TAL
    - Compute `gap_duration = next_onset - (prev_onset + record_duration)`; when `gap_duration > 0`, insert `floor(gap_duration * sample_rate)` NaN values into each signal's accumulator
    - Promote signal accumulators from `int16` to `float32` before gap insertion (NaN cannot be represented as int16)
    - Raise `ValueError(record_index, overlap_duration)` when `gap_duration < 0` (overlapping records)
    - _Requirements: 8.1, 8.2, 8.4, 8.5_

  - [ ]* 7.3 Write unit tests for `_records.py`
    - Selective loading: reading 1 of 3 signals reads ≈ 1/3 of data bytes (mock `f.seek` to verify)
    - EDF+C: record onsets computed as `record_index * record_duration` without reading TALs
    - EDF+D: gaps between records produce correct NaN count in output arrays
    - EDF+D: missing time-keeping TAL raises `ValueError` with record index
    - EDF+D: overlapping records raise `ValueError` with record index and overlap duration
    - `num_records == -1` inferred from file size
    - _Requirements: 4.1, 8.1–8.5, 10.23_

  - [ ]* 7.4 Write property tests for `_records.py`
    - **Property 13: EDF+D gap NaN count matches formula** — for any `gap_duration > 0` and `sample_rate > 0`, NaN count in output equals `floor(gap_duration * sample_rate)`
    - _Requirements: 8.2_


- [x] 8. Implement top-level reader and wire everything together (`reader.py` + `__init__.py`)
  - [x] 8.1 Implement `read_edf()` in `reader.py`
    - Signature: `read_edf(source: str | pathlib.Path | BinaryIO, *, physical: bool = True, dtype: numpy.dtype | type | None = None, tzinfo: datetime.tzinfo | None = None) -> EDFFile`
    - Validate `source` type; raise `TypeError(which method missing)` if BinaryIO lacks `.read()` or `.seek()`
    - Raise `TypeError(argument name, received type)` if `tzinfo` is not `datetime.tzinfo` (and not `None`)
    - Raise `ValueError` if `dtype` is provided and `physical=False`
    - Open file from path (raise `FileNotFoundError(path)` or `PermissionError(path)` appropriately)
    - Read header bytes and call `parse_global_header` and `parse_signal_headers`
    - Validate `header_bytes == 256 + ns * 256` (raise `ValueError("malformed header")`)
    - Build header-only `Signal` stubs (no sample data) for non-annotation channels
    - For EDF+/EDF+D: read all annotation bytes up-front and call `parse_tals` to build `annotations` list; sort by onset
    - Construct and return `EDFFile` with open file handle, `_physical`, and `_dtype`
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.11, 10.1, 10.2, 10.3, 10.10, 10.11, 10.12, 10.13, 10.14, 10.17_

  - [x] 8.2 Implement `EDFFile.read_signals()` (wire `_records.py` and `_scaler.py`)
    - `read_signals(signals: Sequence[str] | Sequence[int] = ()) -> list[Signal]`
    - Resolve empty `signals` → all non-annotation channel indices in file order
    - Resolve label strings → indices via label lookup; raise `KeyError(label)` for unknowns
    - Resolve integer indices; raise `IndexError(index)` for out-of-range
    - Preserve caller-requested order in returned list (not file order)
    - Call `read_signal_data(f, header, signal_headers, sorted(unique_indices))`
    - For each resolved signal: call `scale_signal(raw, sh, dtype)` if `physical=True`, else keep raw `int16`
    - Construct new `Signal` objects with loaded samples and return in requested order
    - _Requirements: 10.18, 10.19, 10.20, 10.21, 10.22, 10.23_

  - [x] 8.3 Populate `__init__.py` exports
    - `from edfplus.reader import read_edf`
    - `from edfplus._models import EDFFile, EDFHeader, SignalHeader, Signal, Annotation`
    - `__all__ = ["read_edf", "EDFFile", "EDFHeader", "SignalHeader", "Signal", "Annotation"]`
    - _Requirements: 10.1_


- [x] 9. Checkpoint — run full test suite
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Unit tests for `reader.py` end-to-end flows (`test_reader.py`)
  - [x] 10.1 Write unit tests for `read_edf` error handling and API contract
    - `read_edf("nonexistent.edf")` raises `FileNotFoundError` with path in message
    - `read_edf("/etc/shadow")` raises `PermissionError` with path (or skip if running as root)
    - `read_edf(b"notabio")` raises `TypeError` identifying missing method
    - `tzinfo` not a `datetime.tzinfo` instance raises `TypeError` with argument name and type
    - `dtype` + `physical=False` raises `ValueError`
    - `read_edf` importable as `from edfplus import read_edf`
    - Returned `EDFFile` has `.header`, `.signals`, `.annotations` properties
    - Context manager: `with read_edf(...) as f:` — file closed after block
    - _Requirements: 1.2, 1.6, 2.11, 10.1, 10.3, 10.10, 10.11, 10.12, 10.14, 10.17_

  - [x] 10.2 Write unit tests for `read_signals` API
    - `read_signals()` (empty) returns all non-annotation signals in file order
    - `read_signals(["EEG Fpz-Cz"])` returns list with one `Signal` with loaded samples
    - `read_signals([0, 2])` returns signals at indices 0 and 2 in that order
    - `read_signals(["Z", "A"])` returns signals in the provided order, not file order
    - `read_signals(["unknown"])` raises `KeyError("unknown")`
    - `read_signals([999])` raises `IndexError(999)`
    - `Signal.samples` dtype is `float64` by default; `float32` when `dtype=numpy.float32`
    - `Signal.digital_samples()` returns `int16` array
    - _Requirements: 10.18–10.23, 4.7, 4.8_

  - [ ]* 10.3 Write property tests for `reader.py` / `_models.py`
    - **Property 5: Invalid version bytes rejected** — any 8-byte sequence ≠ `b"0       "` causes `read_edf` to raise `ValueError`
    - **Property 10: timestamps() co-length + correct indexing** — for any loaded `Signal` with `n` samples, `len(timestamps()) == n` and `timestamps()[i] == i / sample_rate` for non-NaN `i`
    - **Property 11: datetimes() co-length** — `len(datetimes()) == len(samples)` and each non-NaT element equals `start_datetime + timedelta(seconds=timestamps()[i])`
    - **Property 12: NaN co-location in samples and timestamps()** — `isnan(samples)` equals `isnan(timestamps())` element-wise for EDF+D signals
    - **Property 14: read_signals subset returns same samples as full load** — any subset `S` of indices: `read_signals(S)[k].samples == read_signals()[i_k].samples` element-wise
    - **Property 15: read_signals preserves caller-requested order** — any permutation of labels: returned list order matches input order
    - _Requirements: 1.3, 4.10, 4.11, 8.2, 10.18, 10.19, 10.20_


- [x] 11. Integration tests against the real PSG file (`test_reader.py` integration section)
  - [x] 11.1 Write integration tests using `tests/ST7011J0-PSG.edf`
    - `read_edf("tests/ST7011J0-PSG.edf")` returns `EDFFile` without error
    - `edf.header.variant` is one of `"EDF"`, `"EDF+C"`, `"EDF+D"`
    - `edf.header.num_signals >= 1`
    - `edf.header.start_datetime` is a valid `datetime` object
    - `edf.signals` is a non-empty list; all items are `Signal` instances
    - `read_signals()` loads all channels; each `Signal.samples` is a non-empty `float64` ndarray
    - `Signal.sample_rate > 0` for all signals
    - `Signal.timestamps()` length equals `len(Signal.samples)`
    - `Signal.datetimes()` length equals `len(Signal.samples)`
    - If file is EDF+, `edf.annotations` is a list (may be empty); all items are `Annotation` instances
    - `read_signals([0])` returns same samples as `read_signals()[0].samples`
    - _Requirements: 1.1, 4.1, 4.2, 4.3, 4.10, 4.11, 7.4, 10.4, 10.7, 10.9_

- [x] 12. Final checkpoint — ensure full test suite passes
  - Run `uv run pytest tests/ -v` and verify all tests pass (including property tests at min 100 examples each).
  - Run `uv run ruff check --fix` and `uv run ruff format` to confirm zero lint/format errors.
  - Run `uv run ty check` to confirm zero type errors.
  - Ensure all tests pass, ask the user if questions arise.


## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- The two checkpoints (tasks 9 and 12) validate incremental progress
- Property tests use Hypothesis with `max_examples=100` (do not reduce)
- Every property test must include a comment: `# Feature: edf-file-reader, Property N: <title>`
- `int16` arrays cannot represent NaN — EDF+D signal accumulators must be promoted to `float32` before gap insertion; `_scaler.py` handles NaN passthrough
- The file handle in `EDFFile` stays open across `read_signals()` calls for lazy loading; always use the context manager or call `.close()` when done
- `Signal` objects returned from `read_signals()` are not stored back into `EDFFile.signals`; callers hold them
- All modules use Google-style docstrings, 4-space indent, 120-char line length (ruff config)

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3"] },
    { "id": 2, "tasks": ["2.4", "3.1", "3.2"] },
    { "id": 3, "tasks": ["3.3", "4.1"] },
    { "id": 4, "tasks": ["4.2", "5.1"] },
    { "id": 5, "tasks": ["4.3", "5.2", "6.1"] },
    { "id": 6, "tasks": ["5.3", "6.2"] },
    { "id": 7, "tasks": ["6.3", "7.1"] },
    { "id": 8, "tasks": ["6.4", "7.2"] },
    { "id": 9, "tasks": ["7.3", "8.1"] },
    { "id": 10, "tasks": ["7.4", "8.2"] },
    { "id": 11, "tasks": ["8.3"] },
    { "id": 12, "tasks": ["10.1", "10.2"] },
    { "id": 13, "tasks": ["10.3", "11.1"] }
  ]
}
```
