# Bugfix Requirements Document

## Introduction

The TAL (Time-stamped Annotations List) parser in `src/edfplus/_tal.py` and the header parser in `src/edfplus/_header.py` contain two categories of bugs that prevent the `edfplus` package from functioning:

1. **Python 2-style `except` syntax** — Three `except` statements use the comma-separated form (`except ValueError, OverflowError:`) which is invalid in Python 3 and raises a `SyntaxError` on import.
2. **Incorrect TAL block parsing when duration is absent** — The parser splits TAL blocks on the `0x15` byte to separate onset from the rest, but when duration is absent the `0x15` byte is also absent per the EDF+ spec. This causes onset parsing to fail on time-keeping TALs (e.g. `+0\x14\x14\x00`) because the `0x14`-delimited text bytes are included in the onset string.

Together these bugs cause all `TestPSGIntegration` tests to fail — the first bug prevents import entirely, and the second bug causes annotation parsing failures on real EDF+ files.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the `edfplus` package is imported THEN the system raises a `SyntaxError` due to invalid Python 2-style `except ValueError, OverflowError:` syntax in `_tal.py` line 187 and `_header.py` lines 217 and 228

1.2 WHEN a TAL block has no duration (onset directly followed by `0x14`, e.g. time-keeping TAL `+0\x14\x14\x00`) THEN the system fails to parse the onset because splitting on `0x15` yields a single part containing both the onset and the `0x14`-delimited text bytes concatenated together, and `float("+0\x14\x14")` raises a `ValueError`

1.3 WHEN a TAL block has no duration and no `0x15` byte THEN the system treats the entire block as a single part with no text section, losing all annotation text content

### Expected Behavior (Correct)

2.1 WHEN the `edfplus` package is imported THEN the system SHALL import successfully without any `SyntaxError`

2.2 WHEN a TAL block has no duration (onset directly followed by `0x14`) THEN the system SHALL split on the first `0x14` byte to isolate the onset+duration portion, determine that no `0x15` is present within it (meaning no duration), parse only the onset value, and correctly identify the remaining `0x14`-delimited segments as the text section

2.3 WHEN a TAL block has no duration and contains annotation text (e.g. `+1.5\x14Sleep stage W\x14\x00`) THEN the system SHALL correctly parse the onset as `1.5`, duration as `None`, and extract the annotation text strings from the `0x14`-delimited text section

### Unchanged Behavior (Regression Prevention)

3.1 WHEN a TAL block includes a duration (onset followed by `0x15`, then duration, then `0x14`, then text) THEN the system SHALL CONTINUE TO correctly parse onset, duration, and annotation texts

3.2 WHEN a TAL block is a time-keeping entry with duration present (e.g. `+567\x15\x14\x14\x00`) THEN the system SHALL CONTINUE TO return the onset as `timekeeping_onset` and exclude it from the annotation list

3.3 WHEN `_parse_onset` receives a valid numeric onset string (e.g. `"+1.5"`, `"-0.25"`, `"+0"`) THEN the system SHALL CONTINUE TO return the correct float value

3.4 WHEN `_parse_onset` receives an invalid onset string THEN the system SHALL CONTINUE TO raise `ValueError` with the record index and raw string

3.5 WHEN header date/time fields contain valid values (e.g. `"01.02.85"`) THEN the system SHALL CONTINUE TO parse them correctly without error
