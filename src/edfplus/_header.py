"""EDF/EDF+ header parsing.

This module provides functions for parsing the fixed 256-byte global header and
the variable-length per-signal header block from a raw EDF/EDF+ binary stream.

Functions:
    parse_global_header: Parse the 256-byte global header into an ``EDFHeader``.
    parse_signal_headers: Parse the ``ns × 256``-byte per-signal header block into
        a list of ``Signal`` objects.
"""

from __future__ import annotations

import datetime
from typing import Literal

from edfplus._models import EDFHeader, Signal

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _decode_field(data: bytes, start: int, length: int) -> str:
    """Extract and decode a fixed-width ASCII field from a byte buffer.

    Args:
        data: Source byte buffer.
        start: Start offset (inclusive).
        length: Number of bytes to read.

    Returns:
        Decoded ASCII string with surrounding spaces preserved (caller strips
        as needed).
    """
    return data[start : start + length].decode("ascii", errors="replace")


def _parse_int(raw: str, field_name: str) -> int:
    """Parse a stripped ASCII string as a decimal integer.

    Args:
        raw: The raw (stripped) string value.
        field_name: Human-readable field name used in error messages.

    Returns:
        Parsed integer value.

    Raises:
        ValueError: If the string cannot be converted to int.
    """
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"Cannot parse field '{field_name}' as integer: {raw!r}")


def _parse_float(raw: str, field_name: str) -> float:
    """Parse a stripped ASCII string as a decimal float.

    Args:
        raw: The raw (stripped) string value.
        field_name: Human-readable field name used in error messages.

    Returns:
        Parsed float value.

    Raises:
        ValueError: If the string cannot be converted to float.
    """
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"Cannot parse field '{field_name}' as float: {raw!r}")


def _apply_two_digit_year(yy: int) -> int:
    """Convert a two-digit year to a four-digit year using the EDF century rule.

    The EDF specification states that ``yy >= 85`` maps to 19xx and ``yy < 85``
    maps to 20xx.

    Args:
        yy: Two-digit year value in ``[0, 99]``.

    Returns:
        Four-digit year.
    """
    return 1900 + yy if yy >= 85 else 2000 + yy


def _parse_subfield(value: str) -> str | None:
    """Apply EDF+ subfield semantics: ``"X"`` → ``None``, underscores → spaces.

    Args:
        value: Raw subfield string (already stripped).

    Returns:
        ``None`` if value is ``"X"``, otherwise the value with underscores
        replaced by spaces.
    """
    if value == "X":
        return None
    return value.replace("_", " ")


def _parse_edf_date(raw: str, field_label: str) -> datetime.date:
    """Parse an EDF+ ``dd-MMM-yyyy`` date string into a ``datetime.date``.

    Args:
        raw: The raw subfield string (e.g. ``"02-MAR-1974"``).
        field_label: Human-readable label used in error messages.

    Returns:
        Parsed ``datetime.date``.

    Raises:
        ValueError: If ``raw`` cannot be parsed as ``dd-MMM-yyyy``.
    """
    try:
        return datetime.datetime.strptime(raw, "%d-%b-%Y").date()
    except ValueError:
        raise ValueError(field_label, raw)


# ---------------------------------------------------------------------------
# EDF+ patient / recording subfield parsers
# ---------------------------------------------------------------------------


def _parse_patient_subfields(
    raw: str,
) -> tuple[str | None, str | None, datetime.date | None, str | None]:
    """Parse the EDF+ local patient identification subfields.

    The field is space-delimited with four positional subfields in order:
    hospital code, sex, birthdate (``dd-MMM-yyyy``), and patient name.
    Any subfield whose value is ``"X"`` is returned as ``None``.
    Underscores within a non-``None`` value are replaced with spaces.

    Args:
        raw: Stripped local patient identification string.

    Returns:
        A 4-tuple: ``(patient_code, patient_sex, patient_birthdate, patient_name)``.

    Raises:
        ValueError: If the birthdate subfield is present, not ``"X"``, and
            cannot be parsed as ``dd-MMM-yyyy``.
    """
    parts = raw.split(" ")
    # Pad to at least 4 parts so positional access is always safe.
    while len(parts) < 4:
        parts.append("X")

    patient_code = _parse_subfield(parts[0])
    patient_sex = _parse_subfield(parts[1])
    birthdate_raw = parts[2]
    patient_name = _parse_subfield(parts[3])

    patient_birthdate: datetime.date | None
    if birthdate_raw == "X":
        patient_birthdate = None
    else:
        parsed = _parse_subfield(birthdate_raw)
        if parsed is None:
            patient_birthdate = None
        else:
            patient_birthdate = _parse_edf_date(parsed, "local patient identification birthdate")

    return patient_code, patient_sex, patient_birthdate, patient_name


def _parse_recording_subfields(
    raw: str,
) -> tuple[datetime.date | None, str | None, str | None, str | None]:
    """Parse the EDF+ local recording identification subfields.

    The EDF+ recording identification field begins with the literal keyword
    ``"Startdate"`` followed by four positional subfields: startdate
    (``dd-MMM-yyyy``), investigation/admin code, investigator/technician code, and
    equipment code.  Any subfield whose value is ``"X"`` is returned as ``None``.
    Underscores within a non-``None`` value are replaced with spaces.

    Args:
        raw: Stripped local recording identification string.  Typically has the form
            ``"Startdate dd-MMM-yyyy admin tech equip"`` or
            ``"Startdate X X X X"``.

    Returns:
        A 4-tuple: ``(recording_startdate, recording_admin_code,
        recording_technician, recording_equipment)``.

    Raises:
        ValueError: If the startdate subfield is present, not ``"X"``, and
            cannot be parsed as ``dd-MMM-yyyy``.
    """
    parts = raw.split(" ")
    # The EDF+ recording ID starts with the literal keyword "Startdate".
    # If present, skip it so that the four data subfields start at index 1.
    if parts and parts[0].lower() == "startdate":
        parts = parts[1:]

    # Pad to at least 4 parts so positional access is always safe.
    while len(parts) < 4:
        parts.append("X")

    startdate_raw = parts[0]
    recording_admin_code = _parse_subfield(parts[1])
    recording_technician = _parse_subfield(parts[2])
    recording_equipment = _parse_subfield(parts[3])

    recording_startdate: datetime.date | None
    if startdate_raw == "X":
        recording_startdate = None
    else:
        parsed = _parse_subfield(startdate_raw)
        if parsed is None:
            recording_startdate = None
        else:
            recording_startdate = _parse_edf_date(parsed, "local recording identification startdate")

    return recording_startdate, recording_admin_code, recording_technician, recording_equipment


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_global_header(
    data: bytes,
    file_size: int,
    tzinfo: datetime.tzinfo | None,
) -> EDFHeader:
    """Parse the 256-byte EDF/EDF+ global header block.

    Decodes all fixed-offset fields, validates the version byte, detects the
    EDF variant from the reserved field, applies the two-digit year rule, attaches
    timezone info to the resulting time objects, and (for EDF+C/EDF+D) parses the
    structured patient and recording identification subfields.

    Args:
        data: Raw bytes to parse.  Must be at least 256 bytes.
        file_size: Total file size in bytes.  Used by the caller to infer
            ``num_records`` when the on-disk value is ``-1``; the value is stored
            on ``EDFHeader`` as-is (``-1`` when unknown) — inference happens in
            the caller (``reader.py``).
        tzinfo: Optional timezone to attach to ``start_time`` and
            ``start_datetime``.  ``start_date`` is always timezone-naive.

    Returns:
        A fully-populated, frozen ``EDFHeader`` instance.

    Raises:
        ValueError: With message ``"truncated header"`` when ``data`` is shorter
            than 256 bytes.
        ValueError: When the version field is not ``"0       "``.
        ValueError: When any numeric field (``header_bytes``, ``num_records``,
            ``record_duration``, ``ns``) cannot be parsed.
        ValueError: When the reserved field is non-blank and does not start with
            ``"EDF+C"`` or ``"EDF+D"``.
        ValueError: When an EDF+ patient birthdate or recording startdate
            subfield cannot be parsed as ``dd-MMM-yyyy``.
    """
    if len(data) < 256:
        raise ValueError("truncated header")

    # ------------------------------------------------------------------
    # Decode fixed-offset fields
    # ------------------------------------------------------------------
    version_raw = _decode_field(data, 0, 8)
    local_patient_id_raw = _decode_field(data, 8, 80)
    local_recording_id_raw = _decode_field(data, 88, 80)
    start_date_raw = _decode_field(data, 168, 8)
    start_time_raw = _decode_field(data, 176, 8)
    header_bytes_raw = _decode_field(data, 184, 8).strip()
    reserved_raw = _decode_field(data, 192, 44)
    num_records_raw = _decode_field(data, 236, 8).strip()
    record_duration_raw = _decode_field(data, 244, 8).strip()
    ns_raw = _decode_field(data, 252, 4).strip()

    # ------------------------------------------------------------------
    # Validate version
    # ------------------------------------------------------------------
    if version_raw != "0       ":
        raise ValueError(f"Unsupported EDF version: {version_raw!r}")

    # ------------------------------------------------------------------
    # Parse numeric fields (raise ValueError with field name on failure)
    # ------------------------------------------------------------------
    header_bytes = _parse_int(header_bytes_raw, "header_bytes")
    num_records = _parse_int(num_records_raw, "num_records")
    record_duration = _parse_float(record_duration_raw, "record_duration")
    ns = _parse_int(ns_raw, "ns")

    # ------------------------------------------------------------------
    # Detect EDF variant from the reserved field
    # ------------------------------------------------------------------
    reserved_stripped = reserved_raw.strip()
    variant: Literal["EDF", "EDF+C", "EDF+D"]
    if reserved_raw.startswith("EDF+C"):
        variant = "EDF+C"
    elif reserved_raw.startswith("EDF+D"):
        variant = "EDF+D"
    elif reserved_stripped == "":
        variant = "EDF"
    else:
        raise ValueError(f"Unrecognized reserved field value: {reserved_raw!r}")

    # ------------------------------------------------------------------
    # Parse start date (dd.mm.yy)
    # ------------------------------------------------------------------
    try:
        dd_str, mm_str, yy_str = start_date_raw.split(".")
        dd = int(dd_str)
        mm = int(mm_str)
        yy = int(yy_str)
    except ValueError, AttributeError:
        raise ValueError(f"Cannot parse field 'start_date': {start_date_raw!r}")
    year = _apply_two_digit_year(yy)
    try:
        start_date = datetime.date(year, mm, dd)
    except ValueError:
        raise ValueError(f"Cannot parse field 'start_date': {start_date_raw!r}")

    # ------------------------------------------------------------------
    # Parse start time (hh.mm.ss)
    # ------------------------------------------------------------------
    try:
        hh_str, mi_str, ss_str = start_time_raw.split(".")
        hh = int(hh_str)
        mi = int(mi_str)
        ss = int(ss_str)
    except ValueError, AttributeError:
        raise ValueError(f"Cannot parse field 'start_time': {start_time_raw!r}")
    try:
        start_time_naive = datetime.time(hh, mi, ss)
    except ValueError:
        raise ValueError(f"Cannot parse field 'start_time': {start_time_raw!r}")

    # Attach tzinfo if provided.
    start_time = start_time_naive.replace(tzinfo=tzinfo)
    start_datetime_naive = datetime.datetime.combine(start_date, start_time_naive)
    start_datetime = start_datetime_naive.replace(tzinfo=tzinfo)

    # ------------------------------------------------------------------
    # EDF+ patient / recording subfields
    # ------------------------------------------------------------------
    local_patient_id = local_patient_id_raw.strip()
    local_recording_id = local_recording_id_raw.strip()

    if variant in ("EDF+C", "EDF+D"):
        patient_code, patient_sex, patient_birthdate, patient_name = _parse_patient_subfields(local_patient_id)
        recording_startdate, recording_admin_code, recording_technician, recording_equipment = (
            _parse_recording_subfields(local_recording_id)
        )
    else:
        patient_code = None
        patient_sex = None
        patient_birthdate = None
        patient_name = None
        recording_startdate = None
        recording_admin_code = None
        recording_technician = None
        recording_equipment = None

    # ------------------------------------------------------------------
    # Build and return the frozen EDFHeader
    # ------------------------------------------------------------------
    return EDFHeader(
        version=version_raw.strip(),
        local_patient_id=local_patient_id,
        local_recording_id=local_recording_id,
        num_records=num_records,
        record_duration=record_duration,
        num_signals=ns,
        header_bytes=header_bytes,
        variant=variant,
        start_date=start_date,
        start_time=start_time,
        start_datetime=start_datetime,
        patient_code=patient_code,
        patient_sex=patient_sex,
        patient_birthdate=patient_birthdate,
        patient_name=patient_name,
        recording_startdate=recording_startdate,
        recording_admin_code=recording_admin_code,
        recording_technician=recording_technician,
        recording_equipment=recording_equipment,
        _raw_global=data[:256],
        _raw_signals=b"",
    )


def parse_signal_headers(
    data: bytes,
    ns: int,
    record_duration: float,
) -> list[Signal]:
    """Parse the ``ns × 256``-byte EDF/EDF+ per-signal header block.

    EDF stores per-signal header fields in *field-contiguous* order: all labels
    come first (one per signal × 16 bytes), then all transducer types, etc.
    This function strides through the buffer by field width × signal count to
    reconstruct one ``Signal`` per signal.

    Args:
        data: Raw per-signal header bytes.  Must be exactly ``ns × 256`` bytes.
        ns: Number of signals declared in the global header.
        record_duration: Record duration in seconds; used to compute
            ``sample_rate``.  When ``0``, ``sample_rate`` is set to ``0.0``
            rather than raising a ``ZeroDivisionError``.

    Returns:
        A list of ``ns`` ``Signal`` objects in file order.

    Raises:
        ValueError: With message ``"malformed header"`` when ``len(data)``
            does not equal ``ns × 256``.
        ValueError: When any numeric per-signal field (physical min/max,
            digital min/max, samples per record) cannot be parsed.  The error
            message identifies the 0-based signal index, field name, and raw value.
    """
    expected = ns * 256
    if len(data) != expected:
        raise ValueError(f"malformed header: per-signal block is {len(data)} bytes, expected {expected} (ns={ns})")

    # Field definitions: (name, width_per_signal)
    _FIELDS: list[tuple[str, int]] = [
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

    # Build a dict of field_name → list[str] (one entry per signal).
    fields: dict[str, list[str]] = {}
    offset = 0
    for field_name, width in _FIELDS:
        values: list[str] = []
        for _ in range(ns):
            raw = data[offset : offset + width].decode("ascii", errors="replace")
            values.append(raw)
            offset += width
        fields[field_name] = values

    # Construct Signal objects.
    headers: list[Signal] = []
    for i in range(ns):
        label = fields["label"][i].strip()
        transducer_type = fields["transducer_type"][i].strip()
        physical_dimension = fields["physical_dimension"][i].strip()
        prefiltering = fields["prefiltering"][i].strip()

        # Numeric fields — raise ValueError with signal index + field name on failure.
        try:
            physical_min = float(fields["physical_min"][i].strip())
        except ValueError:
            raise ValueError(i, "physical_min", fields["physical_min"][i])

        try:
            physical_max = float(fields["physical_max"][i].strip())
        except ValueError:
            raise ValueError(i, "physical_max", fields["physical_max"][i])

        try:
            digital_min = int(fields["digital_min"][i].strip())
        except ValueError:
            raise ValueError(i, "digital_min", fields["digital_min"][i])

        try:
            digital_max = int(fields["digital_max"][i].strip())
        except ValueError:
            raise ValueError(i, "digital_max", fields["digital_max"][i])

        try:
            samples_per_record = int(fields["samples_per_record"][i].strip())
        except ValueError:
            raise ValueError(i, "samples_per_record", fields["samples_per_record"][i])

        sample_rate = samples_per_record / record_duration if record_duration != 0 else 0.0
        is_annotation = label == "EDF Annotations"

        headers.append(
            Signal(
                label=label,
                transducer_type=transducer_type,
                physical_dimension=physical_dimension,
                physical_min=physical_min,
                physical_max=physical_max,
                digital_min=digital_min,
                digital_max=digital_max,
                prefiltering=prefiltering,
                samples_per_record=samples_per_record,
                sample_rate=sample_rate,
                is_annotation=is_annotation,
                index=i,
            )
        )

    return headers
