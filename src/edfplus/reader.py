"""Top-level EDF/EDF+ file reader.

This module provides :func:`read_edf`, the single public entry point for opening
and parsing EDF/EDF+ binary files.  It orchestrates header parsing, TAL extraction,
and construction of the :class:`~edfplus._models.EDFFile` container.
"""

from __future__ import annotations

import datetime
import pathlib
import weakref
from typing import BinaryIO

import numpy

from edfplus._header import parse_global_header, parse_signal_headers
from edfplus._models import Annotation, EDFFile, Signal
from edfplus._tal import parse_tals


def read_edf(
    source: str | pathlib.Path | BinaryIO,
    *,
    physical: bool = True,
    dtype: numpy.dtype | type | None = None,
    tzinfo: datetime.tzinfo | None = None,
    eager_load_samples: bool = False,
) -> EDFFile:
    """Open and parse an EDF/EDF+ file, returning an :class:`EDFFile`.

    The returned object contains parsed header metadata and wired
    :class:`Signal` instances.  Sample data is loaded lazily on first access
    to ``signal.samples`` or ``signal.load()``, unless ``eager_load_samples``
    is ``True``.

    Args:
        source: Path to the EDF file (as ``str`` or :class:`pathlib.Path`), or an
            open binary file-like object exposing ``.read()`` and ``.seek()``.
        physical: When ``True`` (default), samples are scaled to physical values.
            When ``False``, raw ``int16`` digital values are returned.
        dtype: Optional NumPy dtype to cast scaled physical values to (e.g.
            ``numpy.float32``).  Only valid when ``physical=True``.
        tzinfo: Optional timezone info to attach to the parsed start time and
            start datetime.  ``None`` (default) produces timezone-naive objects.
        eager_load_samples: When ``True``, load all signal samples immediately
            rather than deferring to first access.

    Returns:
        A fully-constructed :class:`EDFFile` with parsed headers, signal instances,
        and (for EDF+ files) annotations.

    Raises:
        TypeError: If ``source`` is not a ``str``, ``pathlib.Path``, or binary
            file-like object; or if the file-like object lacks ``.read()`` or
            ``.seek()``; or if ``tzinfo`` is not a ``datetime.tzinfo`` instance.
        FileNotFoundError: If ``source`` is a path that does not exist.
        PermissionError: If ``source`` is a path without read permission.
        ValueError: If ``dtype`` is provided with ``physical=False``, or if the
            file header is malformed or truncated.
    """
    # ------------------------------------------------------------------
    # Validate tzinfo
    # ------------------------------------------------------------------
    if tzinfo is not None and not isinstance(tzinfo, datetime.tzinfo):
        raise TypeError("tzinfo", type(tzinfo))

    # ------------------------------------------------------------------
    # Validate dtype + physical combination
    # ------------------------------------------------------------------
    if dtype is not None and not physical:
        raise ValueError("dtype cannot be combined with physical=False")

    # ------------------------------------------------------------------
    # Resolve dtype to numpy.dtype
    # ------------------------------------------------------------------
    resolved_dtype: numpy.dtype | None = None
    if dtype is not None:
        resolved_dtype = numpy.dtype(dtype) if not isinstance(dtype, numpy.dtype) else dtype

    # ------------------------------------------------------------------
    # Open or validate source
    # ------------------------------------------------------------------
    f: BinaryIO
    if isinstance(source, (str, pathlib.Path)):
        path = pathlib.Path(source)
        try:
            f = open(path, "rb")  # noqa: SIM115
        except FileNotFoundError:
            raise FileNotFoundError(str(path))
        except PermissionError:
            raise PermissionError(str(path))
    else:
        # Validate BinaryIO-like object
        if not hasattr(source, "read"):
            raise TypeError(".read() method is missing")
        if not hasattr(source, "seek"):
            raise TypeError(".seek() method is missing")
        f = source

    # ------------------------------------------------------------------
    # Determine file size
    # ------------------------------------------------------------------
    f.seek(0, 2)
    file_size = f.tell()
    f.seek(0)

    # ------------------------------------------------------------------
    # Read and parse global header (256 bytes)
    # ------------------------------------------------------------------
    global_data = f.read(256)
    if len(global_data) < 256:
        f.close()
        raise ValueError("truncated header")

    header = parse_global_header(global_data, file_size, tzinfo)

    # ------------------------------------------------------------------
    # Validate header_bytes == 256 + ns * 256
    # ------------------------------------------------------------------
    ns = header.num_signals
    expected_header_bytes = 256 + ns * 256
    if header.header_bytes != expected_header_bytes:
        f.close()
        raise ValueError("malformed header")

    # ------------------------------------------------------------------
    # Read and parse per-signal headers (ns * 256 bytes)
    # ------------------------------------------------------------------
    signal_data = f.read(ns * 256)
    if len(signal_data) < ns * 256:
        f.close()
        raise ValueError("truncated header")

    all_signals = parse_signal_headers(signal_data, ns, header.record_duration)

    # ------------------------------------------------------------------
    # Update EDFHeader with raw signal bytes (frozen dataclass workaround)
    # ------------------------------------------------------------------
    object.__setattr__(header, "_raw_signals", signal_data)

    # ------------------------------------------------------------------
    # Infer num_records if -1
    # ------------------------------------------------------------------
    num_records = header.num_records
    if num_records == -1:
        bytes_per_record = sum(sig.samples_per_record * 2 for sig in all_signals)
        if bytes_per_record > 0:
            num_records = (file_size - header.header_bytes) // bytes_per_record
        else:
            num_records = 0
        object.__setattr__(header, "num_records", num_records)

    # ------------------------------------------------------------------
    # Compute byte layout for per-signal reading
    # ------------------------------------------------------------------
    bytes_per_signal = [sig.samples_per_record * 2 for sig in all_signals]
    total_bytes_per_record = sum(bytes_per_signal)

    for i, sig in enumerate(all_signals):
        sig._byte_offset_in_record = sum(bytes_per_signal[:i])
        sig._bytes_per_record = total_bytes_per_record
        sig._edf_header = header
        sig._physical = physical
        sig._dtype = resolved_dtype

    # ------------------------------------------------------------------
    # Filter non-annotation signals
    # ------------------------------------------------------------------
    signals: list[Signal] = [sig for sig in all_signals if not sig.is_annotation]

    # ------------------------------------------------------------------
    # For EDF+ variants: read all annotation data and parse TALs
    # ------------------------------------------------------------------
    annotations: list[Annotation] = []
    record_onsets: list[float] = []

    if header.variant in ("EDF+C", "EDF+D"):
        # Find the annotation signal index and its byte position within a record
        annotation_idx: int | None = None
        for i, sig in enumerate(all_signals):
            if sig.is_annotation:
                annotation_idx = i
                break

        if annotation_idx is not None:
            ann_sig = all_signals[annotation_idx]
            ann_bytes_per_record = ann_sig.samples_per_record * 2

            # Offset of annotation signal within a single record
            ann_offset_in_record = sum(bytes_per_signal[:annotation_idx])

            # Read annotation bytes from every record
            for record_idx in range(num_records):
                record_start = header.header_bytes + record_idx * total_bytes_per_record
                f.seek(record_start + ann_offset_in_record)
                ann_data = f.read(ann_bytes_per_record)

                timekeeping_onset, record_annotations = parse_tals(ann_data, record_idx)
                annotations.extend(record_annotations)

                # Store record onsets for EDF+D gap handling
                if timekeeping_onset is not None:
                    record_onsets.append(timekeeping_onset)

            # Sort annotations by onset
            annotations.sort(key=lambda a: a.onset)

    # ------------------------------------------------------------------
    # Construct EDFFile
    # ------------------------------------------------------------------
    edf_file = EDFFile(
        header=header,
        signals=signals,
        annotations=annotations,
        _f=f,
        _all_signals=all_signals,
        _record_onsets=record_onsets,
    )

    # ------------------------------------------------------------------
    # Wire weakrefs on each non-annotation signal
    # ------------------------------------------------------------------
    edf_ref = weakref.ref(edf_file)
    for sig in signals:
        sig._edf_file = edf_ref

    # ------------------------------------------------------------------
    # Eager load if requested
    # ------------------------------------------------------------------
    if eager_load_samples:
        for sig in signals:
            sig._ensure_loaded()

    return edf_file
