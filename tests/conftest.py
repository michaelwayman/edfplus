"""Shared test fixtures and helpers for building synthetic EDF byte blobs.

These helpers construct legally-formatted EDF binary data programmatically so that
property-based and unit tests can drive the parser without relying on real EDF files.

EDF global header layout (256 bytes total, all ASCII):
    version          :  8 bytes  offset   0
    local_patient_id : 80 bytes  offset   8
    local_recording_id: 80 bytes offset  88
    start_date       :  8 bytes  offset 168
    start_time       :  8 bytes  offset 176
    header_bytes     :  8 bytes  offset 184
    reserved         : 44 bytes  offset 192
    num_records      :  8 bytes  offset 236
    record_duration  :  8 bytes  offset 244
    ns               :  4 bytes  offset 252

Per-signal header layout (ns × 256 bytes total, field-contiguous):
    label            : ns × 16 bytes
    transducer_type  : ns × 80 bytes
    physical_dimension: ns ×  8 bytes
    physical_min     : ns ×  8 bytes
    physical_max     : ns ×  8 bytes
    digital_min      : ns ×  8 bytes
    digital_max      : ns ×  8 bytes
    prefiltering     : ns × 80 bytes
    samples_per_record: ns ×  8 bytes
    reserved         : ns × 32 bytes
"""

from __future__ import annotations

import struct
from typing import Any

# ---------------------------------------------------------------------------
# Global header builder
# ---------------------------------------------------------------------------

# Field definitions: (name, width) in order of appearance in the 256-byte header.
_GLOBAL_FIELDS: list[tuple[str, int]] = [
    ("version", 8),
    ("local_patient_id", 80),
    ("local_recording_id", 80),
    ("start_date", 8),
    ("start_time", 8),
    ("header_bytes", 8),
    ("reserved", 44),
    ("num_records", 8),
    ("record_duration", 8),
    ("ns", 4),
]

# Sensible defaults for every global header field.
_GLOBAL_DEFAULTS: dict[str, str] = {
    "version": "0",
    "local_patient_id": "X X X X",
    "local_recording_id": "Startdate X X X X",
    "start_date": "01.01.00",
    "start_time": "00.00.00",
    "header_bytes": "",  # computed dynamically from ns when blank
    "reserved": "",
    "num_records": "1",
    "record_duration": "1",
    "ns": "",  # computed dynamically when blank
}


def make_global_header(**fields: Any) -> bytes:
    """Build a 256-byte EDF global header from keyword arguments.

    Any field not supplied falls back to a sensible default.  The ``ns`` and
    ``header_bytes`` fields are computed automatically from the ``ns`` keyword
    when not explicitly provided.

    Args:
        **fields: EDF global header field values (str or int/float for numeric
            fields).  Supported keys: ``version``, ``local_patient_id``,
            ``local_recording_id``, ``start_date``, ``start_time``,
            ``header_bytes``, ``reserved``, ``num_records``,
            ``record_duration``, ``ns``.

    Returns:
        Exactly 256 bytes of EDF-formatted global header.

    Raises:
        ValueError: If a field value (after conversion to str) exceeds the
            allowed byte width for that field.
    """
    # Resolve ns first so header_bytes can be auto-computed.
    ns_raw = fields.get("ns", _GLOBAL_DEFAULTS["ns"])
    ns_val: int = int(ns_raw) if ns_raw != "" else 1

    merged: dict[str, str] = dict(_GLOBAL_DEFAULTS)
    merged.update({k: str(v) for k, v in fields.items()})

    # Auto-fill ns and header_bytes when not explicitly overridden.
    if "ns" not in fields or merged["ns"] == "":
        merged["ns"] = str(ns_val)
    if "header_bytes" not in fields or merged["header_bytes"] == "":
        merged["header_bytes"] = str(256 + ns_val * 256)

    parts: list[bytes] = []
    for name, width in _GLOBAL_FIELDS:
        raw = merged.get(name, "")
        encoded = raw.encode("ascii", errors="replace")
        if len(encoded) > width:
            raise ValueError(f"Field '{name}' value {encoded!r} exceeds {width} bytes")
        # Pad with ASCII spaces (0x20) on the right to fill the field.
        parts.append(encoded.ljust(width, b" "))

    result = b"".join(parts)
    assert len(result) == 256, f"Global header is {len(result)} bytes, expected 256"
    return result


# ---------------------------------------------------------------------------
# Per-signal header builder
# ---------------------------------------------------------------------------

# Per-signal field definitions: (name, width_per_signal).
_SIGNAL_FIELDS: list[tuple[str, int]] = [
    ("label", 16),
    ("transducer_type", 80),
    ("physical_dimension", 8),
    ("physical_min", 8),
    ("physical_max", 8),
    ("digital_min", 8),
    ("digital_max", 8),
    ("prefiltering", 80),
    ("samples_per_record", 8),
    ("reserved", 32),
]

# Sensible per-signal defaults.
_SIGNAL_DEFAULTS: dict[str, str] = {
    "label": "EEG",
    "transducer_type": "",
    "physical_dimension": "uV",
    "physical_min": "-100",
    "physical_max": "100",
    "digital_min": "-32768",
    "digital_max": "32767",
    "prefiltering": "",
    "samples_per_record": "256",
    "reserved": "",
}


def make_signal_headers(signals: list[dict[str, Any]]) -> bytes:
    """Build the ``ns × 256``-byte EDF per-signal header block.

    EDF stores per-signal header fields in *field-contiguous* order: all
    labels come first (one per signal), then all transducer types, etc.
    This matches the on-disk layout expected by the header parser.

    Args:
        signals: A list of dicts, one per signal.  Each dict may override
            any subset of the per-signal field defaults (``label``,
            ``transducer_type``, ``physical_dimension``, ``physical_min``,
            ``physical_max``, ``digital_min``, ``digital_max``,
            ``prefiltering``, ``samples_per_record``, ``reserved``).

    Returns:
        ``ns × 256`` bytes of EDF-formatted per-signal header data.

    Raises:
        ValueError: If any field value exceeds its allowed byte width.
    """
    ns = len(signals)
    if ns == 0:
        return b""

    parts: list[bytes] = []
    for field_name, width in _SIGNAL_FIELDS:
        for sig in signals:
            raw = str(sig.get(field_name, _SIGNAL_DEFAULTS.get(field_name, "")))
            encoded = raw.encode("ascii", errors="replace")
            if len(encoded) > width:
                raise ValueError(f"Signal field '{field_name}' value {encoded!r} exceeds {width} bytes")
            parts.append(encoded.ljust(width, b" "))

    result = b"".join(parts)
    expected = ns * 256
    assert len(result) == expected, f"Signal headers are {len(result)} bytes, expected {expected}"
    return result


# ---------------------------------------------------------------------------
# Data record builder
# ---------------------------------------------------------------------------


def make_data_record(samples: list[list[int]]) -> bytes:
    """Pack int16 samples into an EDF data record (interleaved by signal).

    EDF data records store all samples for signal 0 first, then all samples
    for signal 1, etc.  Each sample is a little-endian signed 16-bit integer.

    Args:
        samples: A list of sample lists — one inner list per signal.  Each
            inner list contains the ``int16`` sample values for that signal
            within this data record.

    Returns:
        Raw bytes for one data record: all signals concatenated in file order,
        each sample encoded as little-endian int16.
    """
    parts: list[bytes] = []
    for signal_samples in samples:
        parts.append(struct.pack(f"<{len(signal_samples)}h", *signal_samples))
    return b"".join(parts)


# ---------------------------------------------------------------------------
# TAL bytes builder
# ---------------------------------------------------------------------------

# EDF+ TAL control bytes.
_TAL_SEPARATOR = b"\x14"  # separates individual annotation text strings
_TAL_ONSET_SEP = b"\x15"  # separates onset+duration token from text tokens
_TAL_TERMINATOR = b"\x00"  # terminates the TAL block


def make_tal_bytes(annotations: list[tuple[Any, ...]]) -> bytes:
    """Encode a sequence of annotations as EDF+ TAL bytes.

    Each annotation tuple has the form ``(onset, duration_or_none, texts_list)``
    where:

    * ``onset`` — seconds from recording start (numeric, encoded as ASCII decimal).
    * ``duration_or_none`` — duration in seconds, or ``None`` if absent.
    * ``texts_list`` — a list of annotation text strings.

    The TAL byte sequence uses:

    * ``0x14`` (U+0014) to separate individual text strings within one TAL entry.
    * ``0x15`` (U+0015) to separate the onset+duration token from the text section.
    * ``0x00`` to terminate the entire TAL block.

    A leading time-keeping entry (onset with empty text) is included automatically
    for the first annotation if not already present, mimicking the EDF+ on-disk format
    where the first TAL in every data record is the time-keeping TAL.

    Args:
        annotations: A list of ``(onset, duration_or_none, texts_list)`` tuples.
            ``onset`` and ``duration_or_none`` are converted to strings via
            ``str()``.  ``texts_list`` is a list of ``str`` objects.

    Returns:
        TAL-encoded bytes ready to be placed in the EDF+ annotation signal.
    """
    parts: list[bytes] = []
    for onset, duration, texts in annotations:
        # Build the onset+duration token.
        onset_str = str(onset)
        if not onset_str.startswith("-") and not onset_str.startswith("+"):
            onset_str = "+" + onset_str
        token = onset_str.encode("ascii")
        if duration is not None:
            token += _TAL_ONSET_SEP + str(duration).encode("ascii")
        token += _TAL_ONSET_SEP  # separates token from text section

        # Encode text strings separated by 0x14; block ends with 0x14.
        text_bytes = b""
        for text in texts:
            text_bytes += text.encode("ascii") + _TAL_SEPARATOR
        if not texts:
            # Empty text list: just the trailing 0x14 to close the text section.
            text_bytes = _TAL_SEPARATOR

        parts.append(token + text_bytes)

    # Terminate the entire TAL block.
    return b"".join(parts) + _TAL_TERMINATOR
