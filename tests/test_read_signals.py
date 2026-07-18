"""Unit tests for per-signal lazy loading API.

Tests cover signal access by label, by index, lazy loading via .samples,
eager loading via read_edf(..., eager_load_samples=True), dtype casting,
and digital_samples() access.
"""

from __future__ import annotations

import io

import numpy
import pytest
from conftest import make_data_record, make_global_header, make_signal_headers

from edfplus import read_edf

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_edf_bytes(signals_cfg: list[dict[str, str]], num_records: int = 1) -> bytes:
    """Build a minimal synthetic EDF file from signal configuration dicts."""
    ns = len(signals_cfg)
    header = make_global_header(ns=ns, num_records=num_records, record_duration="1")
    sig_headers = make_signal_headers(signals_cfg)

    records = b""
    for _ in range(num_records):
        samples_per_signal = [int(cfg["samples_per_record"]) for cfg in signals_cfg]
        # Use a simple ramp pattern for each signal so values are distinguishable.
        record_data: list[list[int]] = []
        for i, n_samp in enumerate(samples_per_signal):
            record_data.append([i * 100] * n_samp)
        records += make_data_record(record_data)

    return header + sig_headers + records


# Standard 3-signal config used by most tests.
_SIGNALS_CFG = [
    {
        "label": "EEG A",
        "samples_per_record": "256",
        "physical_min": "-100",
        "physical_max": "100",
        "digital_min": "-32768",
        "digital_max": "32767",
    },
    {
        "label": "EEG B",
        "samples_per_record": "128",
        "physical_min": "-200",
        "physical_max": "200",
        "digital_min": "-32768",
        "digital_max": "32767",
    },
    {
        "label": "EEG C",
        "samples_per_record": "64",
        "physical_min": "-50",
        "physical_max": "50",
        "digital_min": "-32768",
        "digital_max": "32767",
    },
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLazyLoadAll:
    """Accessing .samples on each signal loads all non-annotation signals lazily."""

    def test_signals_populated_immediately(self) -> None:
        """edf.signals is populated immediately after read_edf()."""
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes)) as edf:
            assert len(edf.signals) == 3
            assert edf.signals[0].label == "EEG A"
            assert edf.signals[1].label == "EEG B"
            assert edf.signals[2].label == "EEG C"

    def test_samples_lazy_loaded(self) -> None:
        """Accessing .samples triggers lazy load from disk."""
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes)) as edf:
            for sig in edf.signals:
                assert sig._samples is None  # not loaded yet
                _ = sig.samples  # triggers load
                assert sig._samples is not None

    def test_samples_are_float64(self) -> None:
        """Loaded samples default to float64."""
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes)) as edf:
            for sig in edf.signals:
                assert sig.samples.dtype == numpy.float64


class TestEagerLoad:
    """eager_load_samples=True loads all samples immediately."""

    def test_eager_load(self) -> None:
        """With eager_load_samples=True, _samples is populated at construction."""
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes), eager_load_samples=True) as edf:
            for sig in edf.signals:
                assert sig._samples is not None
                assert sig.samples.size > 0


class TestSignalAccessByLabel:
    """edf['label'] selects signals by name."""

    def test_access_by_label(self) -> None:
        """edf['EEG B'] returns the correct signal."""
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes)) as edf:
            sig = edf["EEG B"]
            assert sig.label == "EEG B"
            assert len(sig.samples) == 128

    def test_unknown_label_raises_key_error(self) -> None:
        """Accessing an unknown label raises KeyError."""
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes)) as edf:
            with pytest.raises(KeyError, match="unknown"):
                edf["unknown"]


class TestSignalAccessByIndex:
    """edf[0] selects signals by position."""

    def test_access_by_index(self) -> None:
        """edf[2] returns the third signal."""
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes)) as edf:
            sig = edf[2]
            assert sig.label == "EEG C"

    def test_out_of_range_index_raises_index_error(self) -> None:
        """Accessing an out-of-range index raises IndexError."""
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes)) as edf:
            with pytest.raises(IndexError):
                edf[999]


class TestSignalLoad:
    """signal.load() returns cropped samples."""

    def test_load_no_args_returns_all(self) -> None:
        """load() with no args returns full samples."""
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes)) as edf:
            sig = edf.signals[0]
            numpy.testing.assert_array_equal(sig.load(), sig.samples)

    def test_load_by_index(self) -> None:
        """load(start=10, stop=20) returns 10 samples."""
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes)) as edf:
            sig = edf.signals[0]
            cropped = sig.load(start=10, stop=20)
            assert len(cropped) == 10

    def test_load_by_seconds(self) -> None:
        """load(start=0.0, stop=0.5) for 256 Hz signal returns 128 samples."""
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes)) as edf:
            sig = edf.signals[0]  # 256 Hz
            cropped = sig.load(start=0.0, stop=0.5)
            assert len(cropped) == 128

    def test_load_negative_index(self) -> None:
        """load(start=-10) returns last 10 samples."""
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes)) as edf:
            sig = edf.signals[0]
            cropped = sig.load(start=-10)
            assert len(cropped) == 10
            numpy.testing.assert_array_equal(cropped, sig.samples[-10:])

    def test_load_onset_duration(self) -> None:
        """load(onset=0.0, duration=0.5) for 256 Hz signal returns 128 samples."""
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes)) as edf:
            sig = edf.signals[0]  # 256 Hz
            cropped = sig.load(onset=0.0, duration=0.5)
            assert len(cropped) == 128

    def test_load_start_and_onset_raises(self) -> None:
        """Specifying both start and onset raises ValueError."""
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes)) as edf:
            sig = edf.signals[0]
            with pytest.raises(ValueError, match="start.*onset"):
                sig.load(start=0, onset=0)

    def test_load_stop_and_duration_raises(self) -> None:
        """Specifying both stop and duration raises ValueError."""
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes)) as edf:
            sig = edf.signals[0]
            with pytest.raises(ValueError, match="stop.*duration"):
                sig.load(start=0, stop=10, duration=1.0)


class TestSignalDtype:
    """Signal.samples dtype defaults to float64; float32 when requested."""

    def test_default_dtype_is_float64(self) -> None:
        """By default, physical samples have dtype float64."""
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes)) as edf:
            assert edf.signals[0].samples.dtype == numpy.float64

    def test_dtype_float32(self) -> None:
        """When dtype=numpy.float32, samples are float32."""
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes), dtype=numpy.float32) as edf:
            assert edf.signals[0].samples.dtype == numpy.float32


class TestDigitalSamples:
    """Signal.digital_samples() returns int16 array of raw digital values."""

    def test_digital_samples_dtype_is_int16(self) -> None:
        """digital_samples() returns an int16 array."""
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes), physical=False) as edf:
            digital = edf.signals[0].digital_samples()
            assert digital.dtype == numpy.int16

    def test_digital_samples_values(self) -> None:
        """digital_samples() preserves the raw digital values from the file."""
        # Signal 0 ("EEG A") has all samples set to 0*100 = 0
        edf_bytes = _build_edf_bytes(_SIGNALS_CFG)
        with read_edf(io.BytesIO(edf_bytes), physical=False) as edf:
            digital = edf.signals[0].digital_samples()
            assert numpy.all(digital == 0)

            # Signal 1 ("EEG B") has all samples set to 1*100 = 100
            digital_b = edf.signals[1].digital_samples()
            assert numpy.all(digital_b == 100)
