"""Signal scaling: linear and edffloat (logarithmic) transforms.

Converts raw digital (int16) sample arrays to physical values using either the
standard EDF linear formula or the edffloat logarithmic encoding.
"""

from __future__ import annotations

import re

import numpy

from edfplus._models import Signal

# Regex to parse the edffloat prefiltering field.
# Format: sign*LN[sign*(<dim>)/(<Ymin>)]/(<a>)
# Each capture group is exactly 8 characters.
_EDFFLOAT_RE = re.compile(r"sign\*LN\[sign\*\((.{8})\)/\((.{8})\)\]/\((.{8})\)")


def _is_edffloat(sh: Signal) -> bool:
    """Return True if the signal uses edffloat logarithmic encoding.

    The edffloat condition is:
    - physical_dimension == "Filtered"
    - physical_max == 32767
    - digital_max == 32767
    """
    return sh.physical_dimension == "Filtered" and sh.physical_max == 32767 and sh.digital_max == 32767


def _scale_linear(digital: numpy.ndarray, sh: Signal, dtype: numpy.dtype | None = None) -> numpy.ndarray:
    """Apply the standard EDF linear scaling formula.

    Args:
        digital: Raw digital sample array (int16 or float32 with NaN gaps).
        sh: Signal containing calibration parameters.
        dtype: Optional output dtype; defaults to float64.

    Returns:
        Scaled physical values as a NumPy array.
    """
    # Guard: if digital_max == digital_min, return array filled with physical_min
    if sh.digital_max == sh.digital_min:
        result = numpy.full(digital.shape, sh.physical_min, dtype=numpy.float64)
        # Preserve NaN positions from EDF+D gap insertion (only possible in float arrays)
        if digital.dtype.kind == "f":
            nan_mask = numpy.isnan(digital)
            if nan_mask.any():
                result[nan_mask] = numpy.nan
        if dtype is not None:
            return result.astype(dtype, copy=False)
        return result

    gain = (sh.physical_max - sh.physical_min) / (sh.digital_max - sh.digital_min)

    # Identify NaN positions before scaling (NaN only exists in float arrays from EDF+D gap insertion)
    nan_mask: numpy.ndarray | None = None
    if digital.dtype.kind == "f":
        mask = numpy.isnan(digital)
        if mask.any():
            nan_mask = mask

    # Apply linear formula
    result = sh.physical_min + (digital.astype(numpy.float64) - sh.digital_min) * gain

    # Restore NaN positions
    if nan_mask is not None:
        result[nan_mask] = numpy.nan

    if dtype is not None:
        return result.astype(dtype, copy=False)
    return result


def _scale_edffloat(digital: numpy.ndarray, sh: Signal, dtype: numpy.dtype | None) -> numpy.ndarray:
    """Apply the edffloat logarithmic transform.

    The prefiltering field is parsed for Ymin and a parameters. The three-branch
    transform is applied element-wise:
    - N > 0: Y = Ymin * exp(a * N)
    - N == 0: Y = 0.0
    - N < 0: Y = -Ymin * exp(-a * N)

    Args:
        digital: Raw digital sample array (int16 or float32 with NaN gaps).
        sh: Signal containing prefiltering field with edffloat parameters.
        dtype: Optional output dtype; defaults to float64.

    Returns:
        Scaled physical values as a NumPy array.

    Raises:
        ValueError: If the prefiltering field cannot be parsed, or if Ymin <= 0
            or a <= 0.
    """
    match = _EDFFLOAT_RE.search(sh.prefiltering)
    if match is None:
        raise ValueError(sh.label)

    # Groups: dim (physical dimension), Ymin, a
    _dim_str, ymin_str, a_str = match.group(1), match.group(2), match.group(3)

    try:
        ymin = float(ymin_str)
    except ValueError:
        raise ValueError(sh.label) from None

    try:
        a = float(a_str)
    except ValueError:
        raise ValueError(sh.label) from None

    if ymin <= 0:
        raise ValueError(sh.label)
    if a <= 0:
        raise ValueError(sh.label)

    # Identify NaN positions before applying the transform
    nan_mask: numpy.ndarray | None = None
    if digital.dtype.kind == "f":
        mask = numpy.isnan(digital)
        if mask.any():
            nan_mask = mask

    # Work on a float64 copy to avoid modifying the input
    n = digital.astype(numpy.float64, copy=True)

    # Zero out NaN positions temporarily to avoid warnings in exp()
    if nan_mask is not None:
        n[nan_mask] = 0.0

    # Three-branch transform
    result = numpy.empty_like(n, dtype=numpy.float64)

    pos_mask = n > 0
    neg_mask = n < 0
    zero_mask = n == 0

    result[pos_mask] = ymin * numpy.exp(a * n[pos_mask])
    result[zero_mask] = 0.0
    result[neg_mask] = -ymin * numpy.exp(-a * n[neg_mask])

    # Restore NaN positions
    if nan_mask is not None:
        result[nan_mask] = numpy.nan

    if dtype is not None:
        return result.astype(dtype, copy=False)
    return result


def scale_signal(digital: numpy.ndarray, sh: Signal, dtype: numpy.dtype | None = None) -> numpy.ndarray:
    """Scale a raw digital sample array to physical values.

    Automatically selects between linear scaling and edffloat logarithmic scaling
    based on the signal header fields.

    Args:
        digital: Raw digital sample array. May be int16 (standard) or float32
            (when EDF+D gap insertion has promoted the array and inserted NaN values).
        sh: Signal with calibration and encoding parameters.
        dtype: Optional NumPy dtype to cast the output to. When ``None``, the output
            is ``float64``.

    Returns:
        A NumPy array of physical values with dtype ``float64`` (or ``dtype`` if
        specified). NaN positions from the input are preserved in the output.

    Raises:
        ValueError: If the signal uses edffloat encoding but the prefiltering field
            cannot be parsed, or the parsed Ymin/a values are invalid.
    """
    if _is_edffloat(sh):
        return _scale_edffloat(digital, sh, dtype)
    return _scale_linear(digital, sh, dtype)
