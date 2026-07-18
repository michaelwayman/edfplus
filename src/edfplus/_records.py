"""Data record reading for EDF/EDF+ files.

This module implements :func:`read_signal_data`, which selectively reads raw
``int16`` sample data from the data records portion of an EDF/EDF+ file.  Only
requested signal indices are actually read into memory; non-requested signals
are skipped via relative seeks, achieving memory-efficient selective loading.

For EDF+D (discontinuous) files, the function also handles gap insertion:
when consecutive data records have a time gap (determined from the time-keeping
TAL onset), NaN values are inserted into the signal accumulators to represent
missing samples.
"""

from __future__ import annotations

import math
from typing import BinaryIO

import numpy

from edfplus._models import EDFHeader, Signal
from edfplus._tal import parse_tals


def read_signal_data(
    f: BinaryIO,
    header: EDFHeader,
    signal_headers: list[Signal],
    indices: list[int],
) -> dict[int, numpy.ndarray]:
    """Read raw signal data from EDF/EDF+ data records.

    Seeks to ``header.header_bytes`` and reads the data records portion of the
    file.  For each record, iterates over all signals in file order: requested
    signals are read into memory; non-requested signals are skipped with a
    relative seek.  For EDF+D files, NaN gap samples are inserted between
    records when the time-keeping TAL onsets indicate a discontinuity.

    Args:
        f: Open binary file handle positioned anywhere (the function seeks to
            the correct offset).
        header: Parsed ``EDFHeader`` for the file.
        signal_headers: List of all ``Signal`` objects (including
            annotation channels), in file order.
        indices: Sorted list of 0-based signal indices to load.  These refer to
            positions in ``signal_headers`` and should not include annotation
            channel indices (annotation data is handled internally for EDF+D).

    Returns:
        A dictionary mapping each requested signal index to its concatenated
        raw ``int16`` sample array.  For EDF+D files with gaps, the arrays are
        promoted to ``float32`` and contain NaN values at gap positions.

    Raises:
        ValueError: With ``(record_index,)`` when an EDF+D record is missing
            its time-keeping TAL.
        ValueError: With ``(record_index, overlap_duration)`` when an EDF+D
            record overlaps with its predecessor (negative gap).
    """
    ns = len(signal_headers)

    # Compute bytes per signal per record: each sample is 2 bytes (int16 LE).
    bytes_per_signal = [sh.samples_per_record * 2 for sh in signal_headers]
    bytes_per_record = sum(bytes_per_signal)

    # Determine record count.
    num_records = header.num_records
    if num_records == -1:
        # Infer from file size.
        f.seek(0, 2)  # seek to end
        file_size = f.tell()
        num_records = (file_size - header.header_bytes) // bytes_per_record

    # Identify the annotation channel index (if any) for EDF+D TAL reading.
    annotation_idx: int | None = None
    if header.variant == "EDF+D":
        for i, sh in enumerate(signal_headers):
            if sh.is_annotation:
                annotation_idx = i
                break

    # Build the set of indices we need to actually read (requested + annotation for EDF+D).
    indices_set = set(indices)
    need_annotation_read = (
        header.variant == "EDF+D" and annotation_idx is not None and annotation_idx not in indices_set
    )

    # Accumulators: list of int16 arrays per record for each requested signal.
    accumulators: dict[int, list[numpy.ndarray]] = {idx: [] for idx in indices}

    # For EDF+D: store time-keeping onsets per record.
    record_onsets: list[float] = []

    # Seek to start of data records.
    f.seek(header.header_bytes)

    for record_idx in range(num_records):
        annotation_bytes: bytes | None = None

        for sig_idx in range(ns):
            n_bytes = bytes_per_signal[sig_idx]

            if sig_idx in indices_set:
                # Read this signal's data for this record.
                raw = f.read(n_bytes)
                arr = numpy.frombuffer(raw, dtype=numpy.dtype("<i2"))
                accumulators[sig_idx].append(arr.copy())
            elif need_annotation_read and sig_idx == annotation_idx:
                # Read annotation bytes for EDF+D time-keeping.
                annotation_bytes = f.read(n_bytes)
            else:
                # Skip this signal.
                f.seek(n_bytes, 1)

        # For EDF+D: parse time-keeping onset from annotation signal.
        if header.variant == "EDF+D" and annotation_idx is not None:
            if annotation_idx in indices_set:
                # We already read the annotation signal into the accumulator — but
                # we still need the raw bytes for TAL parsing. Reconstruct from the
                # last appended array.
                ann_arr = accumulators[annotation_idx][-1]
                annotation_bytes = ann_arr.tobytes()

            if annotation_bytes is None:
                # Should not happen if annotation_idx is valid, but guard.
                raise ValueError(record_idx)

            timekeeping_onset, _ = parse_tals(annotation_bytes, record_idx)
            if timekeeping_onset is None:
                raise ValueError(record_idx)
            record_onsets.append(timekeeping_onset)

    # For EDF+D: insert NaN gaps between records.
    if header.variant == "EDF+D" and len(record_onsets) > 1:
        _insert_gaps(accumulators, record_onsets, header.record_duration, signal_headers, indices)

    # Concatenate accumulators into final arrays.
    result: dict[int, numpy.ndarray] = {}
    for idx in indices:
        if accumulators[idx]:
            result[idx] = numpy.concatenate(accumulators[idx])
        else:
            result[idx] = numpy.array([], dtype=numpy.int16)

    return result


def _insert_gaps(
    accumulators: dict[int, list[numpy.ndarray]],
    record_onsets: list[float],
    record_duration: float,
    signal_headers: list[Signal],
    indices: list[int],
) -> None:
    """Insert NaN gap arrays into accumulators for EDF+D discontinuities.

    Processes records in reverse order (to preserve list indices) and inserts
    NaN-filled float32 arrays between consecutive records where a time gap exists.

    Args:
        accumulators: Mutable dict of per-signal record chunk lists.
        record_onsets: Time-keeping onset for each record.
        record_duration: Duration of each data record in seconds.
        signal_headers: All signal headers for sample_rate lookup.
        indices: Requested signal indices.

    Raises:
        ValueError: With ``(record_index, overlap_duration)`` for overlapping records.
    """
    # Check for gaps between consecutive records (process from last to first to
    # keep insertion indices stable).
    needs_promotion = False
    gap_insertions: list[tuple[int, float]] = []  # (insert_after_record_idx, gap_duration)

    for r in range(len(record_onsets) - 1):
        prev_onset = record_onsets[r]
        next_onset = record_onsets[r + 1]
        gap_duration = next_onset - (prev_onset + record_duration)

        if gap_duration < 0:
            raise ValueError(r + 1, abs(gap_duration))
        elif gap_duration > 0:
            gap_insertions.append((r, gap_duration))
            needs_promotion = True

    if not needs_promotion:
        return

    # Promote all existing arrays to float32 (NaN cannot be represented as int16).
    for idx in indices:
        for i, arr in enumerate(accumulators[idx]):
            if arr.dtype != numpy.float32:
                accumulators[idx][i] = arr.astype(numpy.float32)

    # Insert gap arrays in reverse order to preserve indices.
    for r, gap_duration in reversed(gap_insertions):
        for idx in indices:
            sh = signal_headers[idx]
            nan_count = math.floor(gap_duration * sh.sample_rate)
            if nan_count > 0:
                gap_arr = numpy.full(nan_count, numpy.nan, dtype=numpy.float32)
                # Insert after record r (i.e., at position r + 1 in the list).
                accumulators[idx].insert(r + 1, gap_arr)
