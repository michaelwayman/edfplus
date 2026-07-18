"""Unit tests for the Signal dataclass.

Verifies that Signal is a proper dataclass with all header fields as direct
attributes, is mutable (not frozen), and supports lazy sample loading via
the _samples field.
"""

from __future__ import annotations

import dataclasses

import numpy
import pytest

from edfplus._models import Signal


def _make_signal(**overrides: object) -> Signal:
    """Create a Signal instance with sensible defaults, overridable by kwargs."""
    defaults: dict[str, object] = {
        "label": "EEG Fpz-Cz",
        "transducer_type": "AgAgCl electrode",
        "physical_dimension": "uV",
        "physical_min": -3200.0,
        "physical_max": 3200.0,
        "digital_min": -2048,
        "digital_max": 2047,
        "prefiltering": "HP:0.1Hz",
        "samples_per_record": 256,
        "sample_rate": 256.0,
        "is_annotation": False,
        "index": 0,
    }
    defaults.update(overrides)
    return Signal(**defaults)  # type: ignore[arg-type]


class TestSignalIsDataclass:
    """Signal is a proper Python dataclass."""

    def test_is_dataclass(self) -> None:
        """dataclasses.is_dataclass(Signal) returns True."""
        assert dataclasses.is_dataclass(Signal)

    def test_instance_is_dataclass(self) -> None:
        """An instance of Signal is recognized as a dataclass instance."""
        sig = _make_signal()
        assert dataclasses.is_dataclass(sig)

    def test_not_frozen(self) -> None:
        """Signal is not frozen — _samples must be mutable."""
        sig = _make_signal()
        # Should be able to assign to _samples without FrozenInstanceError
        sig._samples = numpy.array([1.0, 2.0, 3.0])
        assert sig._samples is not None


class TestSignalFields:
    """Signal exposes all header fields as direct dataclass attributes."""

    def test_label(self) -> None:
        sig = _make_signal(label="EEG A")
        assert sig.label == "EEG A"

    def test_transducer_type(self) -> None:
        sig = _make_signal(transducer_type="Active electrode")
        assert sig.transducer_type == "Active electrode"

    def test_physical_dimension(self) -> None:
        sig = _make_signal(physical_dimension="mV")
        assert sig.physical_dimension == "mV"

    def test_physical_min_max(self) -> None:
        sig = _make_signal(physical_min=-100.0, physical_max=100.0)
        assert sig.physical_min == -100.0
        assert sig.physical_max == 100.0

    def test_digital_min_max(self) -> None:
        sig = _make_signal(digital_min=-32768, digital_max=32767)
        assert sig.digital_min == -32768
        assert sig.digital_max == 32767

    def test_prefiltering(self) -> None:
        sig = _make_signal(prefiltering="HP:0.5Hz LP:70Hz")
        assert sig.prefiltering == "HP:0.5Hz LP:70Hz"

    def test_samples_per_record(self) -> None:
        sig = _make_signal(samples_per_record=512)
        assert sig.samples_per_record == 512

    def test_sample_rate(self) -> None:
        sig = _make_signal(sample_rate=512.0)
        assert sig.sample_rate == 512.0

    def test_is_annotation(self) -> None:
        sig = _make_signal(is_annotation=True)
        assert sig.is_annotation is True

    def test_index(self) -> None:
        sig = _make_signal(index=3)
        assert sig.index == 3


class TestSignalSamplesProperty:
    """Signal.samples property raises RuntimeError when not loaded."""

    def test_samples_raises_when_not_loaded(self) -> None:
        """Accessing .samples before loading raises RuntimeError."""
        sig = _make_signal()
        with pytest.raises(RuntimeError, match="not wired"):
            _ = sig.samples

    def test_samples_returns_array_when_loaded(self) -> None:
        """Accessing .samples after assignment returns the array."""
        sig = _make_signal()
        arr = numpy.array([1.0, 2.0, 3.0], dtype=numpy.float64)
        sig._samples = arr
        numpy.testing.assert_array_equal(sig.samples, arr)


class TestSignalPrivateFields:
    """Private fields have correct defaults and are excluded from repr."""

    def test_edf_file_default_none(self) -> None:
        sig = _make_signal()
        assert sig._edf_file is None

    def test_edf_header_default_none(self) -> None:
        sig = _make_signal()
        assert sig._edf_header is None

    def test_byte_offset_default_zero(self) -> None:
        sig = _make_signal()
        assert sig._byte_offset_in_record == 0

    def test_bytes_per_record_default_zero(self) -> None:
        sig = _make_signal()
        assert sig._bytes_per_record == 0

    def test_physical_default_true(self) -> None:
        sig = _make_signal()
        assert sig._physical is True

    def test_dtype_default_none(self) -> None:
        sig = _make_signal()
        assert sig._dtype is None

    def test_samples_default_none(self) -> None:
        sig = _make_signal()
        assert sig._samples is None

    def test_private_fields_not_in_repr(self) -> None:
        """Private fields (repr=False) are excluded from repr output."""
        sig = _make_signal()
        r = repr(sig)
        assert "_edf_file" not in r
        assert "_edf_header" not in r
        assert "_byte_offset_in_record" not in r
        assert "_bytes_per_record" not in r
        assert "_physical" not in r
        assert "_dtype" not in r
        assert "_samples" not in r
