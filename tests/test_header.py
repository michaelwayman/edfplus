"""Unit tests for _header.py — parse_global_header (tasks 3.1 and 3.2).

Covers:
- Happy-path field decoding
- Version validation
- Variant detection (EDF, EDF+C, EDF+D, invalid)
- Two-digit year rule
- tzinfo attachment
- EDF+ patient / recording subfield parsing
- Error cases: truncated buffer, bad numeric fields
"""

from __future__ import annotations

import datetime

import pytest
from conftest import make_global_header

from edfplus._header import parse_global_header

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _header(**kwargs) -> bytes:
    """Build a 256-byte global header with sensible defaults."""
    return make_global_header(**kwargs)


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_basic_fields_decoded(self):
        data = _header(
            local_patient_id="MCH-0234567 F 02-MAY-1951 Haagse_Hans",
            local_recording_id="Startdate 02-MAR-2002 EMG_study Dr_Smith equip-1",
            start_date="02.01.85",
            start_time="15.23.47",
            num_records="10",
            record_duration="2",
            ns="3",
        )
        h = parse_global_header(data, file_size=10000, tzinfo=None)
        assert h.version == "0"
        assert h.num_records == 10
        assert h.record_duration == 2.0
        assert h.num_signals == 3
        assert h.header_bytes == 256 + 3 * 256

    def test_start_date_and_time_decoded(self):
        data = _header(start_date="15.06.01", start_time="08.30.00")
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.start_date == datetime.date(2001, 6, 15)
        assert h.start_time == datetime.time(8, 30, 0)
        assert h.start_datetime == datetime.datetime(2001, 6, 15, 8, 30, 0)

    def test_start_time_and_datetime_timezone_naive_by_default(self):
        data = _header()
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.start_time.tzinfo is None
        assert h.start_datetime.tzinfo is None

    def test_start_date_is_always_plain_date(self):
        tz = datetime.timezone.utc
        data = _header()
        h = parse_global_header(data, file_size=1000, tzinfo=tz)
        assert isinstance(h.start_date, datetime.date)
        assert not isinstance(h.start_date, datetime.datetime)

    def test_raw_global_preserved(self):
        data = _header()
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h._raw_global == data[:256]

    def test_raw_signals_is_empty_bytes(self):
        data = _header()
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h._raw_signals == b""

    def test_num_records_minus_one_stored_as_is(self):
        data = _header(num_records="-1")
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.num_records == -1

    def test_local_patient_id_stripped(self):
        data = _header(local_patient_id="  mypatient  ")
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.local_patient_id == "mypatient"

    def test_local_recording_id_stripped(self):
        data = _header(local_recording_id="  myrec  ")
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.local_recording_id == "myrec"

    def test_record_duration_float(self):
        data = _header(record_duration="0.5")
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.record_duration == 0.5


# ---------------------------------------------------------------------------
# Version validation
# ---------------------------------------------------------------------------


class TestVersionValidation:
    def test_valid_version_accepted(self):
        data = _header(version="0")
        # Should not raise
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.version == "0"

    def test_wrong_version_raises(self):
        # Build header with version field padded as "1       "
        raw = bytearray(make_global_header(version="0"))
        raw[0:8] = b"1       "
        with pytest.raises(ValueError, match="version"):
            parse_global_header(bytes(raw), file_size=1000, tzinfo=None)

    def test_wrong_version_message_includes_value(self):
        raw = bytearray(make_global_header(version="0"))
        raw[0:8] = b"2       "
        with pytest.raises(ValueError) as exc_info:
            parse_global_header(bytes(raw), file_size=1000, tzinfo=None)
        assert "2" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Variant detection
# ---------------------------------------------------------------------------


class TestVariantDetection:
    def test_blank_reserved_gives_edf(self):
        data = _header(reserved="")
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.variant == "EDF"

    def test_edf_plus_c_detected(self):
        data = _header(reserved="EDF+C")
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.variant == "EDF+C"

    def test_edf_plus_d_detected(self):
        data = _header(reserved="EDF+D")
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.variant == "EDF+D"

    def test_unrecognized_reserved_raises(self):
        data = _header(reserved="WEIRD")
        with pytest.raises(ValueError):
            parse_global_header(data, file_size=1000, tzinfo=None)

    def test_unrecognized_reserved_message_includes_value(self):
        data = _header(reserved="UNKNOWN_VARIANT")
        with pytest.raises(ValueError) as exc_info:
            parse_global_header(data, file_size=1000, tzinfo=None)
        assert "UNKNOWN_VARIANT" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Two-digit year rule
# ---------------------------------------------------------------------------


class TestTwoDigitYear:
    @pytest.mark.parametrize(
        "yy,expected_year",
        [
            (84, 2084),
            (85, 1985),
            (0, 2000),
            (99, 1999),
            (50, 2050),
            (1, 2001),
        ],
    )
    def test_year_rule(self, yy: int, expected_year: int):
        date_str = f"01.01.{yy:02d}"
        data = _header(start_date=date_str)
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.start_date.year == expected_year


# ---------------------------------------------------------------------------
# tzinfo attachment
# ---------------------------------------------------------------------------


class TestTzinfo:
    def test_tzinfo_attached_to_start_time(self):
        tz = datetime.timezone.utc
        data = _header()
        h = parse_global_header(data, file_size=1000, tzinfo=tz)
        assert h.start_time.tzinfo is tz

    def test_tzinfo_attached_to_start_datetime(self):
        tz = datetime.timezone(datetime.timedelta(hours=5))
        data = _header()
        h = parse_global_header(data, file_size=1000, tzinfo=tz)
        assert h.start_datetime.tzinfo is tz

    def test_tzinfo_none_gives_naive_objects(self):
        data = _header()
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.start_time.tzinfo is None
        assert h.start_datetime.tzinfo is None

    def test_start_date_unaffected_by_tzinfo(self):
        tz = datetime.timezone.utc
        data = _header(start_date="15.06.01")
        h = parse_global_header(data, file_size=1000, tzinfo=tz)
        assert h.start_date == datetime.date(2001, 6, 15)
        # start_date has no tzinfo attribute; just verify it's a plain date
        assert type(h.start_date) is datetime.date


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    def test_truncated_buffer_raises(self):
        with pytest.raises(ValueError, match="truncated header"):
            parse_global_header(b"0       " + b" " * 200, file_size=1000, tzinfo=None)

    def test_empty_buffer_raises(self):
        with pytest.raises(ValueError, match="truncated header"):
            parse_global_header(b"", file_size=0, tzinfo=None)

    def test_non_numeric_ns_raises(self):
        raw = bytearray(make_global_header(version="0"))
        raw[252:256] = b"XXXX"
        with pytest.raises(ValueError):
            parse_global_header(bytes(raw), file_size=1000, tzinfo=None)

    def test_non_numeric_num_records_raises(self):
        raw = bytearray(make_global_header(version="0"))
        raw[236:244] = b"NOTANUM "
        with pytest.raises(ValueError):
            parse_global_header(bytes(raw), file_size=1000, tzinfo=None)

    def test_non_numeric_record_duration_raises(self):
        raw = bytearray(make_global_header(version="0"))
        raw[244:252] = b"NOTANUM "
        with pytest.raises(ValueError):
            parse_global_header(bytes(raw), file_size=1000, tzinfo=None)

    def test_non_numeric_header_bytes_raises(self):
        raw = bytearray(make_global_header(version="0"))
        raw[184:192] = b"NOTANUM "
        with pytest.raises(ValueError):
            parse_global_header(bytes(raw), file_size=1000, tzinfo=None)

    def test_255_bytes_raises_truncated(self):
        data = make_global_header()[:255]
        with pytest.raises(ValueError, match="truncated header"):
            parse_global_header(data, file_size=1000, tzinfo=None)


# ---------------------------------------------------------------------------
# EDF+ patient subfields (task 3.2)
# ---------------------------------------------------------------------------


class TestEDFPlusPatientSubfields:
    def test_edf_plain_subfields_are_none(self):
        data = _header(reserved="")
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.patient_code is None
        assert h.patient_sex is None
        assert h.patient_birthdate is None
        assert h.patient_name is None

    def test_edf_plus_c_subfields_parsed(self):
        data = _header(
            reserved="EDF+C",
            local_patient_id="MCH-0234567 F 02-MAY-1951 Haagse_Hans",
        )
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.patient_code == "MCH-0234567"
        assert h.patient_sex == "F"
        assert h.patient_birthdate == datetime.date(1951, 5, 2)
        assert h.patient_name == "Haagse Hans"  # underscore replaced

    def test_x_subfield_is_none(self):
        data = _header(
            reserved="EDF+C",
            local_patient_id="X X X X",
        )
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.patient_code is None
        assert h.patient_sex is None
        assert h.patient_birthdate is None
        assert h.patient_name is None

    def test_underscore_replaced_with_space_in_patient_name(self):
        data = _header(
            reserved="EDF+C",
            local_patient_id="P001 M X John_Doe",
        )
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.patient_name == "John Doe"

    def test_invalid_birthdate_raises(self):
        data = _header(
            reserved="EDF+C",
            local_patient_id="P001 M BADDATE John",
        )
        with pytest.raises(ValueError) as exc_info:
            parse_global_header(data, file_size=1000, tzinfo=None)
        args = exc_info.value.args
        assert "local patient identification birthdate" in args[0]
        assert "BADDATE" in args[1]

    def test_edf_plus_d_subfields_parsed(self):
        data = _header(
            reserved="EDF+D",
            local_patient_id="CODE M 01-JAN-2000 PatientName",
        )
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.patient_code == "CODE"
        assert h.patient_sex == "M"
        assert h.patient_birthdate == datetime.date(2000, 1, 1)
        assert h.patient_name == "PatientName"


# ---------------------------------------------------------------------------
# EDF+ recording subfields (task 3.2)
# ---------------------------------------------------------------------------


class TestEDFPlusRecordingSubfields:
    def test_edf_plain_recording_subfields_are_none(self):
        data = _header(reserved="")
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.recording_startdate is None
        assert h.recording_admin_code is None
        assert h.recording_technician is None
        assert h.recording_equipment is None

    def test_edf_plus_c_recording_subfields_parsed(self):
        data = _header(
            reserved="EDF+C",
            local_recording_id="Startdate 02-MAR-2002 EMG_study Dr_Smith equip-1",
        )
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.recording_startdate == datetime.date(2002, 3, 2)
        assert h.recording_admin_code == "EMG study"  # underscore replaced
        assert h.recording_technician == "Dr Smith"  # underscore replaced
        assert h.recording_equipment == "equip-1"

    def test_x_recording_subfields_are_none(self):
        data = _header(
            reserved="EDF+C",
            local_recording_id="Startdate X X X X",
        )
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.recording_startdate is None
        assert h.recording_admin_code is None
        assert h.recording_technician is None
        assert h.recording_equipment is None

    def test_invalid_recording_startdate_raises(self):
        data = _header(
            reserved="EDF+C",
            local_recording_id="Startdate BADDATE admin tech equip",
        )
        with pytest.raises(ValueError) as exc_info:
            parse_global_header(data, file_size=1000, tzinfo=None)
        args = exc_info.value.args
        assert "local recording identification startdate" in args[0]
        assert "BADDATE" in args[1]

    def test_underscore_replaced_in_recording_subfield(self):
        data = _header(
            reserved="EDF+C",
            local_recording_id="Startdate 01-JAN-2020 my_study my_tech my_equip",
        )
        h = parse_global_header(data, file_size=1000, tzinfo=None)
        assert h.recording_admin_code == "my study"
        assert h.recording_technician == "my tech"
        assert h.recording_equipment == "my equip"
