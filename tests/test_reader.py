"""Unit tests for read_edf error handling and API contract.

Validates: Requirements 1.2, 1.6, 2.11, 10.1, 10.3, 10.10, 10.11, 10.12, 10.14, 10.17
"""

from __future__ import annotations

import io
import os
import stat
from pathlib import Path
from typing import Any

import numpy
import pytest
from conftest import make_data_record, make_global_header, make_signal_headers

from edfplus import EDFFile, read_edf

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_edf_bytes(ns: int = 1, num_records: int = 1, samples_per_record: int = 256) -> bytes:
    """Build minimal valid EDF file bytes with one signal and one data record."""
    header = make_global_header(ns=ns, num_records=num_records, record_duration="1")
    signals = make_signal_headers([{"label": "EEG", "samples_per_record": str(samples_per_record)}])
    record = make_data_record([[0] * samples_per_record])
    return header + signals + record * num_records


def _write_edf(tmp_path: Path) -> Path:
    """Write a minimal EDF file to tmp_path and return its path."""
    edf_path = tmp_path / "test.edf"
    edf_path.write_bytes(_minimal_edf_bytes())
    return edf_path


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------


class TestReadEdfFileNotFound:
    """Tests that read_edf raises FileNotFoundError for missing files."""

    def test_nonexistent_path_raises_file_not_found(self) -> None:
        """FileNotFoundError raised with path in message for missing file."""
        with pytest.raises(FileNotFoundError, match="nonexistent.edf"):
            read_edf("nonexistent.edf")

    def test_nonexistent_path_object_raises_file_not_found(self) -> None:
        """FileNotFoundError raised for Path objects too."""
        with pytest.raises(FileNotFoundError, match="does_not_exist"):
            read_edf(Path("/tmp/does_not_exist.edf"))


class TestReadEdfPermissionError:
    """Tests that read_edf raises PermissionError for unreadable files."""

    @pytest.mark.skipif(os.getuid() == 0, reason="Running as root — cannot test permission denial")
    def test_unreadable_file_raises_permission_error(self, tmp_path: Path) -> None:
        """PermissionError raised with path in message for unreadable file."""
        edf_path = _write_edf(tmp_path)
        # Remove read permission
        edf_path.chmod(stat.S_IWUSR)
        try:
            with pytest.raises(PermissionError, match=str(edf_path)):
                read_edf(edf_path)
        finally:
            # Restore permissions for cleanup
            edf_path.chmod(stat.S_IRUSR | stat.S_IWUSR)


class TestReadEdfTypeError:
    """Tests that read_edf raises TypeError for invalid source types."""

    def test_bytes_source_raises_type_error(self) -> None:
        """TypeError raised identifying missing method for bytes input."""
        source: Any = b"notabio"
        with pytest.raises(TypeError, match="read"):
            read_edf(source)

    def test_object_without_read_raises_type_error(self) -> None:
        """TypeError raised for objects lacking .read() method."""

        class NoRead:
            def seek(self, pos: int, whence: int = 0) -> int:
                return 0

        source: Any = NoRead()
        with pytest.raises(TypeError, match="read"):
            read_edf(source)

    def test_object_without_seek_raises_type_error(self) -> None:
        """TypeError raised for objects lacking .seek() method."""

        class NoSeek:
            def read(self, n: int = -1) -> bytes:
                return b""

        source: Any = NoSeek()
        with pytest.raises(TypeError, match="seek"):
            read_edf(source)


class TestReadEdfTzinfoTypeError:
    """Tests that read_edf raises TypeError for invalid tzinfo argument."""

    def test_tzinfo_not_tzinfo_instance_raises_type_error(self) -> None:
        """TypeError raised with argument name when tzinfo is wrong type."""
        bad_tzinfo: Any = "UTC"
        with pytest.raises(TypeError, match="tzinfo"):
            read_edf(io.BytesIO(_minimal_edf_bytes()), tzinfo=bad_tzinfo)

    def test_tzinfo_int_raises_type_error(self) -> None:
        """TypeError raised for integer tzinfo."""
        bad_tzinfo: Any = 42
        with pytest.raises(TypeError, match="tzinfo"):
            read_edf(io.BytesIO(_minimal_edf_bytes()), tzinfo=bad_tzinfo)


class TestReadEdfDtypePhysicalFalse:
    """Tests that read_edf raises ValueError for dtype + physical=False."""

    def test_dtype_with_physical_false_raises_value_error(self) -> None:
        """ValueError raised when dtype is set with physical=False."""
        with pytest.raises(ValueError, match="dtype"):
            read_edf(io.BytesIO(_minimal_edf_bytes()), dtype=numpy.float32, physical=False)


# ---------------------------------------------------------------------------
# Import / API contract tests
# ---------------------------------------------------------------------------


class TestReadEdfImport:
    """Tests that read_edf is importable from the public API."""

    def test_importable_from_edfplus(self) -> None:
        """read_edf importable as `from edfplus import read_edf`."""
        from edfplus import read_edf as imported_fn

        assert callable(imported_fn)

    def test_in_all(self) -> None:
        """read_edf listed in edfplus.__all__."""
        import edfplus

        assert "read_edf" in edfplus.__all__


class TestReadEdfReturnedObject:
    """Tests that read_edf returns an EDFFile with expected properties."""

    def test_returns_edffile(self, tmp_path: Path) -> None:
        """read_edf returns an EDFFile instance."""
        edf_path = _write_edf(tmp_path)
        result = read_edf(edf_path)
        try:
            assert isinstance(result, EDFFile)
        finally:
            result.close()

    def test_has_header_property(self, tmp_path: Path) -> None:
        """Returned EDFFile has .header property."""
        edf_path = _write_edf(tmp_path)
        with read_edf(edf_path) as edf:
            assert edf.header is not None
            assert hasattr(edf.header, "num_signals")
            assert hasattr(edf.header, "variant")

    def test_has_signals_property(self, tmp_path: Path) -> None:
        """Returned EDFFile has .signals property (list)."""
        edf_path = _write_edf(tmp_path)
        with read_edf(edf_path) as edf:
            assert isinstance(edf.signals, list)
            assert len(edf.signals) >= 1

    def test_has_annotations_property(self, tmp_path: Path) -> None:
        """Returned EDFFile has .annotations property (list)."""
        edf_path = _write_edf(tmp_path)
        with read_edf(edf_path) as edf:
            assert isinstance(edf.annotations, list)


# ---------------------------------------------------------------------------
# Context manager tests
# ---------------------------------------------------------------------------


class TestReadEdfContextManager:
    """Tests that read_edf supports context manager protocol."""

    def test_context_manager_closes_file(self, tmp_path: Path) -> None:
        """File handle is closed after context manager __exit__."""
        edf_path = _write_edf(tmp_path)
        with read_edf(edf_path) as edf:
            assert not edf._f.closed
        assert edf._f.closed

    def test_context_manager_returns_edffile(self, tmp_path: Path) -> None:
        """Context manager __enter__ returns EDFFile."""
        edf_path = _write_edf(tmp_path)
        with read_edf(edf_path) as edf:
            assert isinstance(edf, EDFFile)

    def test_context_manager_usable_inside_block(self, tmp_path: Path) -> None:
        """EDFFile is fully usable inside the context manager block."""
        edf_path = _write_edf(tmp_path)
        with read_edf(edf_path) as edf:
            assert edf.header.num_signals == 1
            assert len(edf.signals) == 1
            assert edf.signals[0].label == "EEG"

    def test_bytesio_source_works(self) -> None:
        """read_edf accepts a BytesIO source and returns valid EDFFile."""
        bio = io.BytesIO(_minimal_edf_bytes())
        with read_edf(bio) as edf:
            assert isinstance(edf, EDFFile)
            assert edf.header.num_signals == 1
