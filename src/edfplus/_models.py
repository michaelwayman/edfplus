"""Data models for the EDF/EDF+ file reader.

This module defines all public data structures returned by the EDF reader:
``EDFHeader``, ``Annotation``, ``Signal``, and ``EDFFile``.
"""

from __future__ import annotations

import datetime
import weakref
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, BinaryIO, Literal

import numpy

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Frozen dataclasses — pure value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EDFHeader:
    """Parsed global header from a 256-byte EDF/EDF+ header block.

    Attributes:
        version: Version field, always ``"0"`` for a valid EDF file.
        local_patient_id: Raw 80-byte local patient identification field, stripped.
        local_recording_id: Raw 80-byte local recording identification field, stripped.
        num_records: Number of data records in the file (inferred from file size when
            the on-disk value is ``-1``).
        record_duration: Duration of each data record in seconds.
        num_signals: Total number of signals (``ns``), including any EDF Annotations
            signal.
        header_bytes: Total header size in bytes (``256 + ns * 256``).
        variant: EDF variant detected from the reserved field.  One of ``"EDF"``,
            ``"EDF+C"`` (continuous), or ``"EDF+D"`` (discontinuous).
        start_date: Recording start date.  Year is interpreted with the two-digit rule:
            ``yy >= 85`` → 19xx, ``yy < 85`` → 20xx.
        start_time: Recording start time.  Timezone-naive unless a ``tzinfo`` was
            passed to ``read_edf()``.
        start_datetime: Combined ``start_date`` + ``start_time``.  Timezone-naive
            unless a ``tzinfo`` was passed to ``read_edf()``.
        patient_code: Hospital/patient code from the EDF+ patient identification
            subfield; ``None`` for plain EDF or when the subfield is ``"X"``.
        patient_sex: Sex subfield from the EDF+ patient identification; ``None`` for
            plain EDF or ``"X"``.
        patient_birthdate: Parsed birthdate from the EDF+ patient identification
            subfield; ``None`` for plain EDF or ``"X"``.
        patient_name: Patient name from the EDF+ patient identification subfield;
            ``None`` for plain EDF or ``"X"``.
        recording_startdate: Recording start date parsed from the EDF+ recording
            identification subfield; ``None`` for plain EDF or ``"X"``.
        recording_admin_code: Investigation/admin code from the EDF+ recording
            identification subfield; ``None`` for plain EDF or ``"X"``.
        recording_technician: Technician/investigator code from the EDF+ recording
            identification subfield; ``None`` for plain EDF or ``"X"``.
        recording_equipment: Equipment code from the EDF+ recording identification
            subfield; ``None`` for plain EDF or ``"X"``.
        _raw_global: Original 256 bytes of the global header, preserved for
            round-trip fidelity.
        _raw_signals: Original ``ns * 256`` bytes of the per-signal header block,
            preserved for round-trip fidelity.
    """

    # --- Raw decoded fields ---
    version: str
    local_patient_id: str
    local_recording_id: str
    num_records: int
    record_duration: float
    num_signals: int
    header_bytes: int

    # --- Variant ---
    variant: Literal["EDF", "EDF+C", "EDF+D"]

    # --- Parsed date/time ---
    start_date: datetime.date
    start_time: datetime.time
    start_datetime: datetime.datetime

    # --- EDF+ patient subfields (None for plain EDF) ---
    patient_code: str | None
    patient_sex: str | None
    patient_birthdate: datetime.date | None
    patient_name: str | None

    # --- EDF+ recording subfields (None for plain EDF) ---
    recording_startdate: datetime.date | None
    recording_admin_code: str | None
    recording_technician: str | None
    recording_equipment: str | None

    # --- Raw bytes for round-trip fidelity (private) ---
    _raw_global: bytes
    _raw_signals: bytes


@dataclass(frozen=True)
class Annotation:
    """A single EDF+ annotation parsed from a Time-stamped Annotation List (TAL).

    Each ``Annotation`` holds exactly one text string. Multi-text TAL blocks
    produce multiple ``Annotation`` instances sharing the same onset and duration.

    Attributes:
        onset: Onset time in seconds from the recording start.
        duration: Duration of the annotated event in seconds, or ``None`` if the TAL
            entry did not include a duration field.
        text: The annotation text string for this entry.
    """

    onset: float
    duration: float | None
    text: str


# ---------------------------------------------------------------------------
# Signal — dataclass with all header fields + lazy sample loading
# ---------------------------------------------------------------------------


@dataclass
class Signal:
    """A single EDF/EDF+ signal channel with header metadata and lazy sample loading.

    All per-signal header fields are stored directly as dataclass fields.
    Sample data is loaded lazily: accessing the ``samples`` property auto-loads
    from disk on first access (if a parent EDFFile weakref is wired), or raises
    ``RuntimeError`` if the signal is not wired to a file.

    Attributes:
        label: Signal label, stripped of leading/trailing whitespace.
        transducer_type: Transducer type string.
        physical_dimension: Physical dimension (unit) string.
        physical_min: Physical minimum calibration value.
        physical_max: Physical maximum calibration value.
        digital_min: Minimum raw digital (int16) value.
        digital_max: Maximum raw digital (int16) value.
        prefiltering: Pre-filtering description string.
        samples_per_record: Number of samples in each data record for this signal.
        sample_rate: Sample rate in Hz (``samples_per_record / record_duration``).
        is_annotation: ``True`` when this signal is the EDF Annotations channel.
        index: 0-based position of this signal in the file's signal list.
    """

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

    # --- Private fields for lazy loading (not shown in repr) ---
    _edf_file: weakref.ref[EDFFile] | None = field(default=None, repr=False)
    _edf_header: EDFHeader | None = field(default=None, repr=False)
    _byte_offset_in_record: int = field(default=0, repr=False)
    _bytes_per_record: int = field(default=0, repr=False)
    _physical: bool = field(default=True, repr=False)
    _dtype: numpy.dtype | None = field(default=None, repr=False)
    _samples: numpy.ndarray | None = field(default=None, init=False, repr=False)

    # --- Sample access ---

    @property
    def samples(self) -> numpy.ndarray:
        """Loaded sample array (physical float64 by default, or raw int16 if unscaled).

        Auto-loads from disk on first access if wired to an EDFFile.
        """
        self._ensure_loaded()
        assert self._samples is not None  # guaranteed by _ensure_loaded
        return self._samples

    def _ensure_loaded(self) -> None:
        """Load samples from disk if not yet loaded."""
        if self._samples is not None:
            return
        if self._edf_file is None:
            raise RuntimeError(
                f"Sample data for signal {self.label!r} has not been loaded yet. Signal is not wired to an EDFFile."
            )
        edf = self._edf_file()
        if edf is None:
            raise RuntimeError(
                f"Sample data for signal {self.label!r} cannot be loaded: "
                "the parent EDFFile has been garbage collected."
            )
        self._read_own_samples(edf)

    def _read_own_samples(self, edf: EDFFile) -> None:
        """Read this signal's raw samples from disk and optionally scale them.

        Args:
            edf: The parent EDFFile providing the file handle and header info.
        """
        from edfplus._scaler import scale_signal

        f = edf._f
        if f.closed:
            raise RuntimeError(f"Cannot load signal {self.label!r}: the file handle is closed.")

        header = edf._header
        num_records = header.num_records

        samples_per_record = self.samples_per_record
        signal_bytes_per_record = samples_per_record * 2

        # Read raw int16 samples from every record for this signal.
        chunks: list[numpy.ndarray] = []
        for r in range(num_records):
            offset = header.header_bytes + r * self._bytes_per_record + self._byte_offset_in_record
            f.seek(offset)
            raw = f.read(signal_bytes_per_record)
            arr = numpy.frombuffer(raw, dtype=numpy.dtype("<i2")).copy()
            chunks.append(arr)

        # For EDF+D: insert NaN gaps between discontinuous records.
        if header.variant == "EDF+D" and hasattr(edf, "_record_onsets") and len(edf._record_onsets) > 1:
            import math

            record_duration = header.record_duration
            needs_promotion = False
            gap_insertions: list[tuple[int, float]] = []

            for r in range(len(edf._record_onsets) - 1):
                prev_onset = edf._record_onsets[r]
                next_onset = edf._record_onsets[r + 1]
                gap_duration = next_onset - (prev_onset + record_duration)
                if gap_duration > 0:
                    gap_insertions.append((r, gap_duration))
                    needs_promotion = True

            if needs_promotion:
                # Promote to float32 for NaN support.
                for i, arr in enumerate(chunks):
                    chunks[i] = arr.astype(numpy.float32)

                # Insert gaps in reverse order.
                for r, gap_duration in reversed(gap_insertions):
                    nan_count = math.floor(gap_duration * self.sample_rate)
                    if nan_count > 0:
                        gap_arr = numpy.full(nan_count, numpy.nan, dtype=numpy.float32)
                        chunks.insert(r + 1, gap_arr)

        if chunks:
            raw_data = numpy.concatenate(chunks)
        else:
            raw_data = numpy.array([], dtype=numpy.int16)

        # Apply scaling if physical mode.
        if self._physical:
            self._samples = scale_signal(raw_data, self, self._dtype)
        else:
            self._samples = raw_data

    # --- Cropping / loading API ---

    def load(
        self,
        start: int | float | datetime.datetime | datetime.timedelta | None = None,
        stop: int | float | datetime.datetime | datetime.timedelta | None = None,
        *,
        onset: int | float | datetime.datetime | datetime.timedelta | None = None,
        duration: float | datetime.timedelta | None = None,
    ) -> numpy.ndarray:
        """Load and return a slice of the signal's samples.

        Supports flexible cropping by sample index, seconds, datetime, or timedelta.

        Args:
            start: Start position. int=sample index, float=seconds, datetime=absolute,
                timedelta=offset from recording start.
            stop: Stop position (same type interpretation as start).
            onset: Alias for start. Cannot be used together with start.
            duration: Duration from start. float=seconds, timedelta=offset. Cannot be
                used together with stop.

        Returns:
            A NumPy array of the cropped samples.

        Raises:
            ValueError: If both start and onset are specified, or both stop and
                duration are specified.
        """
        self._ensure_loaded()
        assert self._samples is not None
        total_samples = len(self._samples)
        start_idx, stop_idx = self._resolve_bounds(start, stop, onset, duration, total_samples)
        return self._samples[start_idx:stop_idx]

    def load_with_timestamps(
        self,
        start: int | float | datetime.datetime | datetime.timedelta | None = None,
        stop: int | float | datetime.datetime | datetime.timedelta | None = None,
        *,
        onset: int | float | datetime.datetime | datetime.timedelta | None = None,
        duration: float | datetime.timedelta | None = None,
        time_format: Literal["seconds", "datetime"] = "seconds",
    ) -> tuple[numpy.ndarray, numpy.ndarray]:
        """Load samples and corresponding timestamps.

        Args:
            start: Start position (same semantics as ``load()``).
            stop: Stop position (same semantics as ``load()``).
            onset: Alias for start.
            duration: Duration from start.
            time_format: ``"seconds"`` for float64 seconds-from-start timestamps,
                ``"datetime"`` for datetime64[us] absolute timestamps.

        Returns:
            A tuple ``(samples, timestamps)`` where both are NumPy arrays of equal
            length.

        Raises:
            ValueError: If both start and onset are specified, or both stop and
                duration are specified.
        """
        self._ensure_loaded()
        assert self._samples is not None
        total_samples = len(self._samples)
        start_idx, stop_idx = self._resolve_bounds(start, stop, onset, duration, total_samples)
        samples = self._samples[start_idx:stop_idx]

        if time_format == "seconds":
            timestamps = numpy.arange(start_idx, stop_idx, dtype=numpy.float64) / self.sample_rate
        else:
            if self._edf_header is None:
                raise RuntimeError("Cannot compute datetime timestamps without an associated EDFHeader.")
            origin = numpy.datetime64(self._edf_header.start_datetime, "us")
            seconds = numpy.arange(start_idx, stop_idx, dtype=numpy.float64) / self.sample_rate
            delta = (seconds * 1_000_000).astype("timedelta64[us]")
            timestamps = origin + delta

        return samples, timestamps

    def _resolve_bounds(
        self,
        start: int | float | datetime.datetime | datetime.timedelta | None,
        stop: int | float | datetime.datetime | datetime.timedelta | None,
        onset: int | float | datetime.datetime | datetime.timedelta | None,
        duration: float | datetime.timedelta | None,
        total_samples: int,
    ) -> tuple[int, int]:
        """Resolve start/stop/onset/duration to integer sample indices.

        Args:
            start: Start position.
            stop: Stop position.
            onset: Alias for start.
            duration: Duration from resolved start.
            total_samples: Total number of loaded samples.

        Returns:
            A tuple ``(start_idx, stop_idx)`` clamped to ``[0, total_samples]``.

        Raises:
            ValueError: On conflicting parameters.
        """
        if start is not None and onset is not None:
            raise ValueError("Cannot specify both 'start' and 'onset'.")
        if stop is not None and duration is not None:
            raise ValueError("Cannot specify both 'stop' and 'duration'.")

        effective_start = start if start is not None else onset
        effective_stop = stop

        start_idx = self._to_sample_index(effective_start, total_samples, default=0)
        if start_idx < 0:
            start_idx = total_samples + start_idx

        if duration is not None:
            dur_seconds: float
            if isinstance(duration, datetime.timedelta):
                dur_seconds = duration.total_seconds()
            else:
                dur_seconds = duration
            stop_idx = start_idx + int(dur_seconds * self.sample_rate)
        else:
            stop_idx = self._to_sample_index(effective_stop, total_samples, default=total_samples)
            if stop_idx < 0:
                stop_idx = total_samples + stop_idx

        # Clamp to valid range.
        start_idx = max(0, min(start_idx, total_samples))
        stop_idx = max(0, min(stop_idx, total_samples))

        return start_idx, stop_idx

    def _to_sample_index(
        self,
        value: int | float | datetime.datetime | datetime.timedelta | None,
        total_samples: int,
        default: int,
    ) -> int:
        """Convert a position value to a sample index.

        Args:
            value: Position value or None.
            total_samples: Total loaded samples (for negative index wrapping).
            default: Default value when value is None.

        Returns:
            Integer sample index (may be negative for wrap-from-end).
        """
        if value is None:
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value * self.sample_rate)
        if isinstance(value, datetime.datetime):
            if self._edf_header is None:
                raise RuntimeError("Cannot resolve datetime without an associated EDFHeader.")
            seconds = (value - self._edf_header.start_datetime).total_seconds()
            return int(seconds * self.sample_rate)
        if isinstance(value, datetime.timedelta):
            return int(value.total_seconds() * self.sample_rate)
        raise TypeError(f"Unsupported type for position: {type(value).__name__}")

    def physical_samples(self, dtype: numpy.dtype | type | None = None) -> numpy.ndarray:
        """Return the loaded samples as scaled physical values.

        Args:
            dtype: Optional NumPy float dtype to cast the output to.  Defaults to
                ``float64``.

        Returns:
            A NumPy array of physical values.

        Raises:
            RuntimeError: If sample data has not been loaded yet.
        """
        arr = self.samples
        if dtype is not None:
            return arr.astype(dtype, copy=False)
        return arr

    def digital_samples(self) -> numpy.ndarray:
        """Return the loaded samples as raw digital int16 values without scaling.

        Returns:
            A NumPy array with dtype ``int16``.

        Raises:
            RuntimeError: If sample data has not been loaded yet.
        """
        arr = self.samples
        return arr.astype(numpy.int16, copy=False)

    # --- Time arrays ---

    def timestamps(self) -> numpy.ndarray:
        """Return per-sample onset times in seconds from the recording start.

        For sample index ``i``, the onset is ``i / sample_rate``.  For EDF+D signals
        that contain NaN gap-filler values, the corresponding positions in the returned
        array are also ``NaN`` so the two arrays remain positionally aligned.

        Returns:
            A ``float64`` NumPy array of length ``len(samples)``.

        Raises:
            RuntimeError: If sample data has not been loaded yet.
        """
        arr = self.samples  # raises RuntimeError if not loaded
        n = len(arr)
        ts = numpy.arange(n, dtype=numpy.float64) / self.sample_rate
        nan_mask = numpy.isnan(arr)
        if nan_mask.any():
            ts[nan_mask] = numpy.nan
        return ts

    def datetimes(self) -> numpy.ndarray:
        """Return per-sample absolute datetimes as ``numpy.datetime64`` values.

        Each element is ``EDFHeader.start_datetime + timedelta(seconds=onset_i)`` where
        ``onset_i`` comes from ``timestamps()``.  Gap samples (NaN onset) produce
        ``numpy.datetime64('NaT')`` entries.

        Returns:
            A NumPy array of ``datetime64[us]`` values of length ``len(samples)``.

        Raises:
            RuntimeError: If sample data has not been loaded yet.
        """
        if self._edf_header is None:
            raise RuntimeError("Cannot compute datetimes without an associated EDFHeader.")
        ts = self.timestamps()
        origin = numpy.datetime64(self._edf_header.start_datetime, "us")
        delta = (ts * 1_000_000).astype("timedelta64[us]")
        result = origin + delta
        nat_mask = numpy.isnan(ts)
        if nat_mask.any():
            result = result.copy()
            result[nat_mask] = numpy.datetime64("NaT")
        return result


# ---------------------------------------------------------------------------
# EDFFile — top-level container
# ---------------------------------------------------------------------------


class EDFFile:
    """Top-level container returned by ``read_edf()``.

    Holds the parsed header, all wired ``Signal`` instances (with lazy loading),
    and an ``Annotation`` list for EDF+ files.  The underlying file handle is
    kept open for lazy signal loading.  Always use the context-manager protocol
    or call ``close()`` when done.

    Signals are populated immediately upon construction.  Sample data is loaded
    lazily on first access to ``signal.samples`` or ``signal.load()``, unless
    ``eager_load_samples=True`` was passed to ``read_edf()``.

    Args:
        header: Parsed ``EDFHeader``.
        signals: List of non-annotation ``Signal`` instances (wired with weakrefs).
        annotations: List of ``Annotation`` objects from the EDF Annotations channel;
            empty for plain EDF files.
        _f: Open binary file handle for lazy data record reading.
        _all_signals: Full list of all ``Signal`` objects (including annotation
            channels) in file order, needed for byte offset calculation.
        _record_onsets: Per-record time-keeping onsets for EDF+D files.
    """

    def __init__(
        self,
        header: EDFHeader,
        signals: list[Signal],
        annotations: list[Annotation],
        _f: BinaryIO,
        _all_signals: list[Signal] | None = None,
        _record_onsets: list[float] | None = None,
    ) -> None:
        self._header = header
        self._signals = signals
        self._annotations = annotations
        self._f = _f
        self._all_signals = _all_signals or []
        self._record_onsets = _record_onsets or []

    # --- Read-only properties ---

    @property
    def header(self) -> EDFHeader:
        """Parsed global ``EDFHeader``."""
        return self._header

    @property
    def signals(self) -> list[Signal]:
        """Non-annotation ``Signal`` instances in file order (lazy-loading)."""
        return self._signals

    @property
    def annotations(self) -> list[Annotation]:
        """Parsed ``Annotation`` list sorted by onset; empty for plain EDF files."""
        return self._annotations

    # --- Signal access by label or index ---

    def __getitem__(self, key: str | int) -> Signal:
        """Return a ``Signal`` by label or index.

        Args:
            key: Either a label string (exact match after stripping) or a 0-based
                integer index into the non-annotation signal list.

        Returns:
            The matching ``Signal``.

        Raises:
            KeyError: If ``key`` is a string that does not match any signal label.
            IndexError: If ``key`` is an integer that is out of range.
            TypeError: If ``key`` is neither a ``str`` nor an ``int``.
        """
        if isinstance(key, str):
            for sig in self._signals:
                if sig.label == key:
                    return sig
            raise KeyError(key)
        if isinstance(key, int):
            if key < 0 or key >= len(self._signals):
                raise IndexError(key)
            return self._signals[key]
        raise TypeError(f"Signal key must be str or int, got {type(key).__name__!r}")

    # --- Context manager protocol ---

    def __enter__(self) -> EDFFile:
        """Enter the context manager, returning ``self``."""
        return self

    def __exit__(self, *args: object) -> None:
        """Exit the context manager and close the file handle."""
        self.close()

    def close(self) -> None:
        """Close the underlying file handle.

        Safe to call multiple times.
        """
        if self._f and not self._f.closed:
            self._f.close()
