"""Bug condition exploration and fix validation tests for TAL parsing.

These tests target the two bugs in edfplus:
1. Python 2-style except syntax causing SyntaxError on import
2. _parse_tal_block() failing when duration is absent (no 0x15 byte)

**Validates: Requirements 1.1, 1.2, 1.3, 2.2, 2.3**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Strategies for generating valid TAL components
# ---------------------------------------------------------------------------

# Valid onset floats per EDF+ spec: [-999999.999, +999999.999]
# Use a slightly tighter range to avoid :g formatting producing scientific notation
# that rounds outside the valid range (e.g. 999999.5 -> "1e+06" -> 1000000.0).
onset_floats = st.floats(
    min_value=-999999.0,
    max_value=999999.0,
    allow_nan=False,
    allow_infinity=False,
)

# ASCII text strings suitable for annotation text (no control characters 0x00-0x1F)
annotation_texts = st.text(
    alphabet=st.characters(min_codepoint=0x20, max_codepoint=0x7E),
    min_size=1,
    max_size=50,
)


def _build_tal_block_no_duration(onset_str: str, texts: list[str]) -> bytes:
    """Build a TAL block WITHOUT duration: +{onset}\\x14[Text\\x14...]\\x14.

    Format per EDF+ spec when duration is absent:
        +Onset 0x14 Text1 0x14 [Text2 0x14 ...] 0x14

    Note: The trailing 0x00 terminator is NOT included here because
    _parse_tal_block() expects the block with the 0x00 already stripped.
    """
    block = onset_str.encode("ascii")
    # Add 0x14 separator after onset, then each text followed by 0x14
    block += b"\x14"
    for text in texts:
        block += text.encode("ascii") + b"\x14"
    return block


def _format_onset(value: float) -> str:
    """Format an onset float to a string with explicit sign, matching EDF+ convention.

    Handles negative zero and uses fixed-point notation to avoid scientific
    notation producing values that round outside the valid onset range.
    """
    # Treat -0.0 as +0.0 for formatting purposes
    if value == 0.0:
        return "+0"
    if value > 0:
        return f"+{value:g}"
    else:
        return f"{value:g}"


# ---------------------------------------------------------------------------
# Property-based test: Bug Condition - TAL Blocks Without Duration
# ---------------------------------------------------------------------------


class TestBugConditionTALWithoutDuration:
    """Property 1: Bug Condition - TAL Blocks Without Duration Fail to Parse.

    **Validates: Requirements 1.1, 1.2, 1.3, 2.2, 2.3**

    These tests encode the EXPECTED (correct) behavior for TAL blocks without
    duration. On unfixed code, they will FAIL — confirming the bug exists.
    After the fix is applied, they will PASS — confirming the fix works.
    """

    @given(onset=onset_floats, texts=st.lists(annotation_texts, min_size=0, max_size=3))
    @settings(max_examples=50)
    def test_property_no_duration_tal_parses_correctly(self, onset: float, texts: list[str]) -> None:
        """TAL blocks without duration should parse onset, duration=None, and texts.

        **Validates: Requirements 2.2, 2.3**
        """
        from edfplus._tal import _parse_tal_block

        onset_str = _format_onset(onset)
        block = _build_tal_block_no_duration(onset_str, texts)

        result = _parse_tal_block(block, record_index=0, is_first_tal=False)

        assert result is not None, f"Expected parsed result, got None for block: {block!r}"
        parsed_onset, parsed_duration, parsed_texts = result

        # Compare against what float() would produce from the formatted string,
        # since :g format may lose precision for some floats.
        expected_onset = float(onset_str)

        # Onset should parse to the same value as float(onset_str)
        assert parsed_onset == pytest.approx(expected_onset, abs=1e-9), (
            f"Onset mismatch: expected {expected_onset}, got {parsed_onset} for onset_str='{onset_str}'"
        )

        # Duration should be None (it was absent)
        assert parsed_duration is None, f"Expected duration=None, got {parsed_duration}"

        # Texts should match the input texts
        assert parsed_texts == texts, f"Texts mismatch: expected {texts}, got {parsed_texts}"

    # ------------------------------------------------------------------
    # Concrete cases from the design document
    # ------------------------------------------------------------------

    def test_timekeeping_tal_no_duration(self) -> None:
        """Time-keeping TAL: +0\\x14\\x14\\x00 -> onset=0.0, duration=None, texts=[].

        **Validates: Requirements 1.2, 2.2**
        """
        from edfplus._tal import _parse_tal_block

        # Block without trailing 0x00 (already stripped by parse_tals)
        block = b"+0\x14\x14"
        result = _parse_tal_block(block, record_index=0, is_first_tal=True)

        assert result is not None
        onset, duration, texts = result
        assert onset == 0.0
        assert duration is None
        assert texts == []

    def test_annotation_tal_no_duration(self) -> None:
        """Annotation TAL: +1.5\\x14Sleep stage W\\x14\\x00 -> onset=1.5, duration=None, texts=["Sleep stage W"].

        **Validates: Requirements 1.3, 2.3**
        """
        from edfplus._tal import _parse_tal_block

        block = b"+1.5\x14Sleep stage W\x14"
        result = _parse_tal_block(block, record_index=0, is_first_tal=False)

        assert result is not None
        onset, duration, texts = result
        assert onset == 1.5
        assert duration is None
        assert texts == ["Sleep stage W"]

    def test_multi_annotation_tal_no_duration(self) -> None:
        """Multi-annotation TAL: +2.0\\x14Event A\\x14Event B\\x14\\x00 -> onset=2.0, duration=None, texts=["Event A", "Event B"].

        **Validates: Requirements 1.3, 2.3**
        """
        from edfplus._tal import _parse_tal_block

        block = b"+2.0\x14Event A\x14Event B\x14"
        result = _parse_tal_block(block, record_index=0, is_first_tal=False)

        assert result is not None
        onset, duration, texts = result
        assert onset == 2.0
        assert duration is None
        assert texts == ["Event A", "Event B"]


# ---------------------------------------------------------------------------
# Tests for parse_tals() — Annotation flattening (one Annotation per text)
# ---------------------------------------------------------------------------


class TestParseTalsAnnotationFlattening:
    """Verify parse_tals() emits one Annotation per text string.

    Multi-text TAL blocks should produce multiple Annotation instances sharing
    the same onset and duration, each with a single .text value.
    """

    def test_multi_text_tal_produces_multiple_annotations(self) -> None:
        """A TAL with two texts produces two Annotation objects with same onset/duration."""
        from edfplus._tal import parse_tals

        # Record format: timekeeping TAL + annotation TAL with two texts
        # Timekeeping: +0\x14\x14\x00
        # Annotation:  +1.5\x14Event A\x14Event B\x14\x00
        data = b"+0\x14\x14\x00+1.5\x14Event A\x14Event B\x14\x00"
        timekeeping_onset, annotations = parse_tals(data, record_index=0)

        assert timekeeping_onset == 0.0
        assert len(annotations) == 2
        assert annotations[0].onset == 1.5
        assert annotations[0].duration is None
        assert annotations[0].text == "Event A"
        assert annotations[1].onset == 1.5
        assert annotations[1].duration is None
        assert annotations[1].text == "Event B"

    def test_single_text_tal_produces_one_annotation(self) -> None:
        """A TAL with one text produces exactly one Annotation."""
        from edfplus._tal import parse_tals

        data = b"+0\x14\x14\x00+3.0\x1510.0\x14Sleep stage W\x14\x00"
        timekeeping_onset, annotations = parse_tals(data, record_index=0)

        assert timekeeping_onset == 0.0
        assert len(annotations) == 1
        assert annotations[0].onset == 3.0
        assert annotations[0].duration == 10.0
        assert annotations[0].text == "Sleep stage W"

    def test_empty_text_tal_produces_no_annotation(self) -> None:
        """A non-timekeeping TAL with no text strings produces no Annotation."""
        from edfplus._tal import parse_tals

        # Timekeeping: +0\x14\x14\x00
        # Second TAL with onset but empty text section: +5.0\x14\x14\x00
        data = b"+0\x14\x14\x00+5.0\x14\x14\x00"
        timekeeping_onset, annotations = parse_tals(data, record_index=0)

        assert timekeeping_onset == 0.0
        assert len(annotations) == 0

    def test_three_texts_produce_three_annotations(self) -> None:
        """A TAL with three texts produces three Annotation objects."""
        from edfplus._tal import parse_tals

        data = b"+0\x14\x14\x00+2.0\x152.5\x14Alpha\x14Beta\x14Gamma\x14\x00"
        timekeeping_onset, annotations = parse_tals(data, record_index=0)

        assert timekeeping_onset == 0.0
        assert len(annotations) == 3
        for ann in annotations:
            assert ann.onset == 2.0
            assert ann.duration == 2.5
        assert annotations[0].text == "Alpha"
        assert annotations[1].text == "Beta"
        assert annotations[2].text == "Gamma"

    def test_multiple_tals_with_mixed_texts(self) -> None:
        """Multiple TAL blocks each produce their own Annotations."""
        from edfplus._tal import parse_tals

        # Timekeeping + two annotation TALs (1 text each)
        data = b"+0\x14\x14\x00+1.0\x14First\x14\x00+2.0\x14Second\x14\x00"
        timekeeping_onset, annotations = parse_tals(data, record_index=0)

        assert timekeeping_onset == 0.0
        assert len(annotations) == 2
        assert annotations[0].onset == 1.0
        assert annotations[0].text == "First"
        assert annotations[1].onset == 2.0
        assert annotations[1].text == "Second"


# ---------------------------------------------------------------------------
# Property-based test: Preservation - TAL Blocks WITH Duration
# ---------------------------------------------------------------------------

# Duration floats: positive values (duration must be > 0 per EDF+ spec)
duration_floats = st.floats(
    min_value=0.001,
    max_value=999999.999,
    allow_nan=False,
    allow_infinity=False,
)


def _build_tal_block_with_duration(onset_str: str, duration_str: str, texts: list[str]) -> bytes:
    """Build a TAL block WITH duration: +{onset}\\x15{duration}\\x14[Text\\x14...]\\x14.

    Format per EDF+ spec when duration is present:
        +Onset 0x15 Duration 0x14 Text1 0x14 [Text2 0x14 ...] 0x14

    The 0x15 byte separates onset from duration within the token, and the
    first 0x14 terminates the token and begins the text section.

    Note: The trailing 0x00 terminator is NOT included here because
    _parse_tal_block() expects the block with the 0x00 already stripped.
    """
    block = onset_str.encode("ascii")
    block += b"\x15"
    block += duration_str.encode("ascii")
    block += b"\x14"
    # Text section: each text terminated by 0x14
    for text in texts:
        block += text.encode("ascii") + b"\x14"
    return block


class TestPreservationTALWithDuration:
    """Property 2: Preservation - TAL Blocks With Duration Continue To Parse Correctly.

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

    These tests verify that TAL blocks containing a duration field (with 0x15
    separator) continue to parse correctly after the fix is applied. This is
    the preservation property — behavior that MUST NOT change.
    """

    @given(
        onset=onset_floats,
        duration=duration_floats,
        texts=st.lists(annotation_texts, min_size=0, max_size=3),
    )
    @settings(max_examples=50)
    def test_property_with_duration_tal_parses_correctly(self, onset: float, duration: float, texts: list[str]) -> None:
        """TAL blocks with duration should parse onset, duration, and texts correctly.

        **Validates: Requirements 3.1, 3.2**
        """
        from edfplus._tal import _parse_tal_block

        onset_str = _format_onset(onset)
        duration_str = f"{duration:g}"
        block = _build_tal_block_with_duration(onset_str, duration_str, texts)

        result = _parse_tal_block(block, record_index=0, is_first_tal=False)

        assert result is not None, f"Expected parsed result, got None for block: {block!r}"
        parsed_onset, parsed_duration, parsed_texts = result

        # Compare against what float() would produce from the formatted string,
        # since :g format may lose precision for some floats.
        expected_onset = float(onset_str)
        expected_duration = float(duration_str)

        # Onset should parse to the same value as float(onset_str)
        assert parsed_onset == pytest.approx(expected_onset, abs=1e-9), (
            f"Onset mismatch: expected {expected_onset}, got {parsed_onset}"
        )

        # Duration should parse to the same value as float(duration_str)
        assert parsed_duration == pytest.approx(expected_duration, abs=1e-9), (
            f"Duration mismatch: expected {expected_duration}, got {parsed_duration}"
        )

        # Texts should match the input texts
        assert parsed_texts == texts, f"Texts mismatch: expected {texts}, got {parsed_texts}"

    # ------------------------------------------------------------------
    # Concrete preservation cases from the design document
    # ------------------------------------------------------------------

    def test_duration_present_apnea(self) -> None:
        """+567\\x1542.0\\x14Apnea\\x14 -> onset=567.0, duration=42.0, texts=["Apnea"].

        **Validates: Requirements 3.1**
        """
        from edfplus._tal import _parse_tal_block

        # Format: onset 0x15 duration 0x14 text_section (0x14-terminated texts)
        block = b"+567\x1542.0\x14Apnea\x14"
        result = _parse_tal_block(block, record_index=0, is_first_tal=False)

        assert result is not None
        onset, duration, texts = result
        assert onset == 567.0
        assert duration == 42.0
        assert texts == ["Apnea"]

    def test_timekeeping_with_duration_field_empty(self) -> None:
        """+123.456\\x15\\x14\\x14 -> onset=123.456, duration=None, texts=[].

        Time-keeping TAL with empty duration field — the duration portion is
        present syntactically (0x15 exists) but the value between 0x15 and
        0x14 is empty, so duration is None.

        **Validates: Requirements 3.2**
        """
        from edfplus._tal import _parse_tal_block

        # Format: onset 0x15 (empty duration) 0x14 text_section (trailing 0x14)
        block = b"+123.456\x15\x14\x14"
        result = _parse_tal_block(block, record_index=0, is_first_tal=True)

        assert result is not None
        onset, duration, texts = result
        assert onset == pytest.approx(123.456)
        assert duration is None
        assert texts == []

    def test_multi_text_with_duration(self) -> None:
        """+10\\x155.0\\x14Text A\\x14Text B\\x14 -> onset=10.0, duration=5.0, texts=["Text A", "Text B"].

        **Validates: Requirements 3.1**
        """
        from edfplus._tal import _parse_tal_block

        # Format: onset 0x15 duration 0x14 text_section (0x14-terminated texts)
        block = b"+10\x155.0\x14Text A\x14Text B\x14"
        result = _parse_tal_block(block, record_index=0, is_first_tal=False)

        assert result is not None
        onset, duration, texts = result
        assert onset == 10.0
        assert duration == 5.0
        assert texts == ["Text A", "Text B"]


# ---------------------------------------------------------------------------
# Preservation tests for _parse_onset()
# ---------------------------------------------------------------------------


class TestPreservationParseOnset:
    """Preservation tests for _parse_onset() function.

    **Validates: Requirements 3.3, 3.4**

    These tests verify that _parse_onset() continues to correctly parse valid
    onset strings and raise ValueError for invalid ones.
    """

    @given(onset=onset_floats)
    @settings(max_examples=50)
    def test_property_valid_onset_parses_to_correct_float(self, onset: float) -> None:
        """Valid onset strings within range should parse to the correct float.

        **Validates: Requirements 3.3**
        """
        from edfplus._tal import _parse_onset

        onset_str = _format_onset(onset)
        # The expected value is what float() would produce from the formatted string
        expected = float(onset_str)
        result = _parse_onset(onset_str, record_index=0)
        assert result == pytest.approx(expected, abs=1e-9), (
            f"_parse_onset('{onset_str}') returned {result}, expected {expected}"
        )

    def test_valid_positive_onset(self) -> None:
        """_parse_onset("+1.5") -> 1.5.

        **Validates: Requirements 3.3**
        """
        from edfplus._tal import _parse_onset

        assert _parse_onset("+1.5", record_index=0) == 1.5

    def test_valid_negative_onset(self) -> None:
        """_parse_onset("-0.25") -> -0.25.

        **Validates: Requirements 3.3**
        """
        from edfplus._tal import _parse_onset

        assert _parse_onset("-0.25", record_index=0) == -0.25

    def test_valid_zero_onset(self) -> None:
        """_parse_onset("+0") -> 0.0.

        **Validates: Requirements 3.3**
        """
        from edfplus._tal import _parse_onset

        assert _parse_onset("+0", record_index=0) == 0.0

    def test_invalid_onset_non_numeric(self) -> None:
        """_parse_onset("abc") raises ValueError.

        **Validates: Requirements 3.4**
        """
        from edfplus._tal import _parse_onset

        with pytest.raises(ValueError):
            _parse_onset("abc", record_index=0)

    def test_invalid_onset_empty_string(self) -> None:
        """_parse_onset("") raises ValueError.

        **Validates: Requirements 3.4**
        """
        from edfplus._tal import _parse_onset

        with pytest.raises(ValueError):
            _parse_onset("", record_index=0)

    def test_invalid_onset_out_of_range_positive(self) -> None:
        """_parse_onset("+9999999") raises ValueError (out of range).

        **Validates: Requirements 3.4**
        """
        from edfplus._tal import _parse_onset

        with pytest.raises(ValueError):
            _parse_onset("+9999999", record_index=0)

    def test_invalid_onset_out_of_range_negative(self) -> None:
        """_parse_onset("-9999999") raises ValueError (out of range).

        **Validates: Requirements 3.4**
        """
        from edfplus._tal import _parse_onset

        with pytest.raises(ValueError):
            _parse_onset("-9999999", record_index=0)
