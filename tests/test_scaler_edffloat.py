"""Tests for the edffloat scaling path in _scaler.py."""

import math

import numpy
import pytest

from edfplus._models import Signal
from edfplus._scaler import scale_signal


def _make_edffloat_header(
    prefiltering: str = "sign*LN[sign*(Filtered)/(0.000100)]/(0.000200)",
    label: str = "EEG",
) -> Signal:
    """Create a Signal that triggers the edffloat path."""
    return Signal(
        label=label,
        transducer_type="AgAgCl electrode",
        physical_dimension="Filtered",
        physical_min=-32767.0,
        physical_max=32767.0,
        digital_min=-32767,
        digital_max=32767,
        prefiltering=prefiltering,
        samples_per_record=256,
        sample_rate=256.0,
        is_annotation=False,
        index=0,
    )


def _make_linear_header() -> Signal:
    """Create a Signal that uses the linear scaling path."""
    return Signal(
        label="EEG Fpz-Cz",
        transducer_type="AgAgCl electrode",
        physical_dimension="uV",
        physical_min=-3200.0,
        physical_max=3200.0,
        digital_min=-2048,
        digital_max=2047,
        prefiltering="HP:0.1Hz",
        samples_per_record=256,
        sample_rate=256.0,
        is_annotation=False,
        index=0,
    )


class TestEdffloatDetection:
    """Tests that edffloat is correctly detected based on header fields."""

    def test_edffloat_detected_when_all_conditions_met(self) -> None:
        """Edffloat path is used when physical_dimension=='Filtered', physical_max==32767, digital_max==32767."""
        sh = _make_edffloat_header()
        digital = numpy.array([1, 0, -1], dtype=numpy.float64)
        result = scale_signal(digital, sh, None)
        # N=1 should give Ymin * exp(a * 1) = 0.0001 * exp(0.0002)
        ymin = 0.0001
        a = 0.0002
        expected_pos = ymin * math.exp(a * 1)
        assert result[0] == pytest.approx(expected_pos)

    def test_linear_when_physical_dimension_not_filtered(self) -> None:
        """Linear path is used when physical_dimension is not 'Filtered'."""
        sh = _make_linear_header()
        digital = numpy.array([0], dtype=numpy.int16)
        result = scale_signal(digital, sh, None)
        # Linear: physical_min + (0 - digital_min) * gain
        gain = (3200.0 - (-3200.0)) / (2047 - (-2048))
        expected = -3200.0 + (0 - (-2048)) * gain
        assert result[0] == pytest.approx(expected)


class TestEdffloatTransform:
    """Tests for the edffloat three-branch transform."""

    def test_positive_n(self) -> None:
        """N > 0 produces Y = Ymin * exp(a * N)."""
        sh = _make_edffloat_header()
        ymin = 0.0001
        a = 0.0002
        digital = numpy.array([5, 10, 100], dtype=numpy.float64)
        result = scale_signal(digital, sh, None)
        for i, n in enumerate([5, 10, 100]):
            expected = ymin * math.exp(a * n)
            assert result[i] == pytest.approx(expected), f"Failed for N={n}"

    def test_zero_n(self) -> None:
        """N == 0 produces Y = 0.0."""
        sh = _make_edffloat_header()
        digital = numpy.array([0], dtype=numpy.float64)
        result = scale_signal(digital, sh, None)
        assert result[0] == 0.0

    def test_negative_n(self) -> None:
        """N < 0 produces Y = -Ymin * exp(-a * N)."""
        sh = _make_edffloat_header()
        ymin = 0.0001
        a = 0.0002
        digital = numpy.array([-5, -10, -100], dtype=numpy.float64)
        result = scale_signal(digital, sh, None)
        for i, n in enumerate([-5, -10, -100]):
            expected = -ymin * math.exp(-a * n)
            assert result[i] == pytest.approx(expected), f"Failed for N={n}"

    def test_mixed_values(self) -> None:
        """Mixed positive, zero, and negative values are handled correctly."""
        sh = _make_edffloat_header()
        ymin = 0.0001
        a = 0.0002
        digital = numpy.array([3, 0, -3], dtype=numpy.float64)
        result = scale_signal(digital, sh, None)
        assert result[0] == pytest.approx(ymin * math.exp(a * 3))
        assert result[1] == 0.0
        assert result[2] == pytest.approx(-ymin * math.exp(-a * (-3)))


class TestEdffloatNanPassthrough:
    """Tests that NaN positions are preserved through edffloat scaling."""

    def test_nan_preserved(self) -> None:
        """NaN values in input remain NaN in output."""
        sh = _make_edffloat_header()
        digital = numpy.array([1.0, numpy.nan, -1.0, numpy.nan, 0.0], dtype=numpy.float64)
        result = scale_signal(digital, sh, None)
        assert numpy.isnan(result[1])
        assert numpy.isnan(result[3])
        assert not numpy.isnan(result[0])
        assert not numpy.isnan(result[2])
        assert not numpy.isnan(result[4])

    def test_all_nan(self) -> None:
        """All-NaN input produces all-NaN output."""
        sh = _make_edffloat_header()
        digital = numpy.array([numpy.nan, numpy.nan, numpy.nan], dtype=numpy.float64)
        result = scale_signal(digital, sh, None)
        assert numpy.all(numpy.isnan(result))


class TestEdffloatDtype:
    """Tests that dtype casting works for edffloat output."""

    def test_default_dtype_is_float64(self) -> None:
        """Output is float64 by default."""
        sh = _make_edffloat_header()
        digital = numpy.array([1, 0, -1], dtype=numpy.float64)
        result = scale_signal(digital, sh, None)
        assert result.dtype == numpy.float64

    def test_cast_to_float32(self) -> None:
        """Output is cast to float32 when dtype=numpy.float32."""
        sh = _make_edffloat_header()
        digital = numpy.array([1, 0, -1], dtype=numpy.float64)
        result = scale_signal(digital, sh, numpy.dtype(numpy.float32))
        assert result.dtype == numpy.float32


class TestEdffloatErrors:
    """Tests for edffloat error conditions."""

    def test_invalid_prefiltering_raises_valueerror(self) -> None:
        """ValueError raised with signal label when prefiltering doesn't match regex."""
        sh = _make_edffloat_header(prefiltering="invalid prefiltering string", label="MySignal")
        digital = numpy.array([1, 0, -1], dtype=numpy.float64)
        with pytest.raises(ValueError, match="MySignal"):
            scale_signal(digital, sh, None)

    def test_ymin_zero_raises_valueerror(self) -> None:
        """ValueError raised when Ymin == 0."""
        # Ymin is 0.000000 (8 chars)
        sh = _make_edffloat_header(prefiltering="sign*LN[sign*(Filtered)/(0.000000)]/(0.000200)", label="BadSig")
        digital = numpy.array([1], dtype=numpy.float64)
        with pytest.raises(ValueError, match="BadSig"):
            scale_signal(digital, sh, None)

    def test_ymin_negative_raises_valueerror(self) -> None:
        """ValueError raised when Ymin < 0."""
        # Ymin is -0.00010 (8 chars)
        sh = _make_edffloat_header(prefiltering="sign*LN[sign*(Filtered)/(-0.00010)]/(0.000200)", label="BadSig")
        digital = numpy.array([1], dtype=numpy.float64)
        with pytest.raises(ValueError, match="BadSig"):
            scale_signal(digital, sh, None)

    def test_a_zero_raises_valueerror(self) -> None:
        """ValueError raised when a == 0."""
        # a is 0.000000 (8 chars)
        sh = _make_edffloat_header(prefiltering="sign*LN[sign*(Filtered)/(0.000100)]/(0.000000)", label="BadSig")
        digital = numpy.array([1], dtype=numpy.float64)
        with pytest.raises(ValueError, match="BadSig"):
            scale_signal(digital, sh, None)

    def test_a_negative_raises_valueerror(self) -> None:
        """ValueError raised when a < 0."""
        # a is -0.00020 (8 chars)
        sh = _make_edffloat_header(prefiltering="sign*LN[sign*(Filtered)/(0.000100)]/(-0.00020)", label="BadSig")
        digital = numpy.array([1], dtype=numpy.float64)
        with pytest.raises(ValueError, match="BadSig"):
            scale_signal(digital, sh, None)

    def test_non_numeric_ymin_raises_valueerror(self) -> None:
        """ValueError raised when Ymin cannot be parsed as float."""
        sh = _make_edffloat_header(prefiltering="sign*LN[sign*(Filtered)/(abcdefgh)]/(0.000200)", label="BadSig")
        digital = numpy.array([1], dtype=numpy.float64)
        with pytest.raises(ValueError, match="BadSig"):
            scale_signal(digital, sh, None)

    def test_non_numeric_a_raises_valueerror(self) -> None:
        """ValueError raised when a cannot be parsed as float."""
        sh = _make_edffloat_header(prefiltering="sign*LN[sign*(Filtered)/(0.000100)]/(xxxxxxxx)", label="BadSig")
        digital = numpy.array([1], dtype=numpy.float64)
        with pytest.raises(ValueError, match="BadSig"):
            scale_signal(digital, sh, None)


class TestLinearScaling:
    """Basic tests for the linear scaling path to ensure it coexists with edffloat."""

    def test_linear_scaling(self) -> None:
        """Standard linear scaling formula produces correct results."""
        sh = _make_linear_header()
        digital = numpy.array([-2048, 0, 2047], dtype=numpy.int16)
        result = scale_signal(digital, sh, None)
        gain = (3200.0 - (-3200.0)) / (2047 - (-2048))
        expected = [-3200.0 + (d - (-2048)) * gain for d in [-2048, 0, 2047]]
        for i in range(3):
            assert result[i] == pytest.approx(expected[i])

    def test_linear_digital_max_equals_min(self) -> None:
        """When digital_max == digital_min, return array filled with physical_min."""
        sh = Signal(
            label="Flat",
            transducer_type="",
            physical_dimension="uV",
            physical_min=-100.0,
            physical_max=100.0,
            digital_min=0,
            digital_max=0,
            prefiltering="",
            samples_per_record=10,
            sample_rate=10.0,
            is_annotation=False,
            index=0,
        )
        digital = numpy.array([0, 0, 0], dtype=numpy.int16)
        result = scale_signal(digital, sh, None)
        assert numpy.all(result == -100.0)

    def test_linear_nan_passthrough(self) -> None:
        """NaN values in input remain NaN in linear scaling output."""
        sh = _make_linear_header()
        digital = numpy.array([1.0, numpy.nan, -1.0], dtype=numpy.float64)
        result = scale_signal(digital, sh, None)
        assert numpy.isnan(result[1])
        assert not numpy.isnan(result[0])
        assert not numpy.isnan(result[2])
