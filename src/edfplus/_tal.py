"""TAL (Time-stamped Annotations List) parser for EDF+ annotation channels.

This module implements :func:`parse_tals`, which decodes the raw bytes from an
EDF+ ``"EDF Annotations"`` signal data record into a list of
:class:`~edfplus._models.Annotation` objects.

TAL on-disk format (per EDF+ spec)::

    With duration:    +Onset 0x15 Duration 0x14 Text1 0x14 [Text2 0x14 ...] 0x00
    Without duration: +Onset 0x14 Text1 0x14 [Text2 0x14 ...] 0x00

* ``0x15`` — separates onset from the optional duration within the
  onset+duration token.  When duration is absent, ``0x15`` is also absent.
* ``0x14`` — terminates the onset+duration token and separates/terminates each
  annotation text string in the text section.
* ``0x00`` — terminates the TAL block; unused trailing bytes in the record are
  also ``0x00``.

The *first* TAL in every EDF+ data record is the **time-keeping TAL**: it
carries a numeric onset (seconds from recording start) and has an empty text
section.  Its onset is returned as ``timekeeping_onset`` and the entry itself
is excluded from the returned annotation list.
"""

from __future__ import annotations

from edfplus._models import Annotation

# ---------------------------------------------------------------------------
# TAL control bytes
# ---------------------------------------------------------------------------

_ONSET_SEP: int = 0x15  # separates onset from optional duration within the token
_TEXT_SEP: int = 0x14  # terminates onset+duration token; separates annotation texts
_TERMINATOR: int = 0x00  # terminates one TAL block; also used as zero-padding

# Onset range mandated by the EDF+ spec (seconds from recording start).
_ONSET_MIN: float = -999999.999
_ONSET_MAX: float = +999999.999


def parse_tals(
    data: bytes,
    record_index: int,
) -> tuple[float | None, list[Annotation]]:
    """Parse EDF+ TAL bytes from a single data record's annotation signal.

    Scans ``data`` for TAL blocks delimited by ``0x00`` bytes, decodes each
    block's onset, optional duration, and annotation texts, and returns them
    as a list of :class:`~edfplus._models.Annotation` objects.

    The *first* TAL in the record is always the **time-keeping TAL**: it has a
    numeric onset and an empty text section.  Its onset is extracted and
    returned separately as ``timekeeping_onset``; the entry is **not** included
    in the returned annotation list.

    Args:
        data: Raw bytes from the EDF Annotations signal for one data record.
            The length must be ``samples_per_record * 2`` bytes; any shortfall
            should have been detected by the caller before invoking this
            function (see ``ValueError`` below).
        record_index: 0-based index of the data record being parsed.  Included
            in ``ValueError`` messages for diagnostics.

    Returns:
        A ``(timekeeping_onset, annotations)`` tuple where:

        * ``timekeeping_onset`` is the ``float`` onset of the first TAL
          (time-keeping entry), or ``None`` if the record contained no TALs.
        * ``annotations`` is a list of :class:`~edfplus._models.Annotation`
          objects for every non-time-keeping TAL whose text list is non-empty
          after discarding empty strings.

    Raises:
        ValueError: With ``(record_index, raw_onset)`` as arguments when an
            onset field cannot be decoded as a decimal number or its value
            falls outside ``[-999999.999, +999999.999]``.
    """
    annotations: list[Annotation] = []
    timekeeping_onset: float | None = None
    is_first_tal = True

    # Split on 0x00 to get individual TAL blocks.  Unused trailing bytes are
    # 0x00 so we may get empty segments — skip those.
    tal_blocks = data.split(b"\x00")

    for raw_block in tal_blocks:
        if not raw_block:
            # Empty block — trailing padding or adjacent terminators; skip.
            continue

        annotation = _parse_tal_block(raw_block, record_index, is_first_tal)
        if annotation is None:
            # Block contained no parseable content after stripping.
            continue

        onset, duration, texts = annotation

        if is_first_tal:
            # The first TAL is the time-keeping entry; extract its onset and
            # do not add it to the annotation list.
            timekeeping_onset = onset
            is_first_tal = False
            continue

        is_first_tal = False

        # Emit one Annotation per text string; skip if no texts.
        for t in texts:
            annotations.append(Annotation(onset=onset, duration=duration, text=t))

    return timekeeping_onset, annotations


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_tal_block(
    block: bytes,
    record_index: int,
    is_first_tal: bool,  # noqa: ARG001  — reserved for future use / clarity
) -> tuple[float, float | None, list[str]] | None:
    """Parse a single null-stripped TAL block into (onset, duration, texts).

    Implements the correct EDF+ TAL parsing algorithm:

    1. Split on the first ``0x14`` byte to separate the onset+duration token
       from the text section.
    2. Within the onset+duration token, check for ``0x15``:
       - If present: split on ``0x15`` — first part is onset, second is duration.
       - If absent: the entire token is the onset, duration is ``None``.
    3. The text section (everything after the first ``0x14``) is split on
       ``0x14`` to extract individual annotation text strings (empty strings
       are discarded).

    On-disk TAL format::

        With duration:    +Onset 0x15 Duration 0x14 Text1 0x14 [Text2 0x14 ...] 0x14
        Without duration: +Onset 0x14 Text1 0x14 [Text2 0x14 ...] 0x14

    Args:
        block: Raw bytes of one TAL block, with the ``0x00`` terminator
            already removed.
        record_index: 0-based data record index (for error messages).
        is_first_tal: Whether this is the first TAL in the record (used by the
            caller to decide time-keeping handling; not used internally here).

    Returns:
        ``(onset_float, duration_float_or_None, texts_list)`` or ``None`` if
        the block is empty after processing.

    Raises:
        ValueError: With ``(record_index, raw_onset_str)`` when the onset
            cannot be parsed or is out of range.
    """
    if not block:
        return None

    text_sep = bytes([_TEXT_SEP])
    onset_sep = bytes([_ONSET_SEP])

    # Step 1: Split on the first 0x14 to separate onset+duration token from
    # the text section.  If no 0x14 is present the block is malformed but we
    # tolerate it by treating the entire block as the token with no text.
    if text_sep in block:
        token, text_section = block.split(text_sep, maxsplit=1)
    else:
        token = block
        text_section = b""

    # Step 2: Within the token, check for 0x15 to separate onset from duration.
    if onset_sep in token:
        onset_raw, duration_raw_bytes = token.split(onset_sep, maxsplit=1)
        # Parse duration
        duration_str = duration_raw_bytes.decode("ascii", errors="replace").strip()
        if duration_str:
            try:
                duration: float | None = float(duration_str)
            except ValueError:
                # Malformed duration — treat as absent rather than raising,
                # since the spec only mandates error handling for onset.
                duration = None
        else:
            # Empty duration field (e.g. onset 0x15 with nothing before 0x14)
            duration = None
    else:
        # No 0x15 — duration is absent; the entire token is the onset.
        onset_raw = token
        duration = None

    # Parse onset
    raw_onset_str = onset_raw.decode("ascii", errors="replace")
    onset = _parse_onset(raw_onset_str, record_index)

    # Step 3: Parse text strings from the text section (split on 0x14,
    # discard empty strings).
    texts = _parse_texts(text_section)

    return onset, duration, texts


def _parse_onset(raw: str, record_index: int) -> float:
    """Parse and validate an EDF+ onset string.

    Args:
        raw: ASCII decimal onset string (e.g. ``"+1.5"`` or ``"-0.25"``).
        record_index: 0-based data record index (for error messages).

    Returns:
        Validated onset as a Python ``float``.

    Raises:
        ValueError: With ``(record_index, raw)`` when ``raw`` cannot be parsed
            as a decimal number or falls outside ``[-999999.999, +999999.999]``.
    """
    stripped = raw.strip()
    try:
        value = float(stripped)
    except ValueError, OverflowError:
        raise ValueError(record_index, stripped)

    if not (_ONSET_MIN <= value <= _ONSET_MAX):
        raise ValueError(record_index, stripped)

    return value


def _parse_texts(section: bytes) -> list[str]:
    """Decode annotation text strings from the text section of a TAL block.

    The text section is a sequence of strings, each terminated by a ``0x14``
    (TEXT_SEP) byte.  Empty strings (from adjacent ``0x14 0x14`` pairs or a
    leading/trailing ``0x14``) are discarded.

    Args:
        section: Raw bytes of the text section (after the last ``0x15``
            separator in the TAL block).

    Returns:
        List of non-empty decoded text strings.
    """
    if not section:
        return []

    sep_byte = bytes([_TEXT_SEP])
    raw_parts = section.split(sep_byte)

    texts: list[str] = []
    for part in raw_parts:
        text = part.decode("ascii", errors="replace").strip()
        if text:
            texts.append(text)

    return texts
