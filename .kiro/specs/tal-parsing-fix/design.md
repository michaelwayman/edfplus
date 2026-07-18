# TAL Parsing Fix Bugfix Design

## Overview

The `edfplus` package has two bugs that prevent it from functioning:

1. **Python 2-style `except` syntax** — Three `except` statements use the comma-separated form (`except ValueError, OverflowError:`) which Python 3 interprets as binding the exception to a variable, not as catching multiple types. This causes a `SyntaxError` on import.
2. **Incorrect TAL block parsing when duration is absent** — `_parse_tal_block()` splits on `0x15` first. Per the EDF+ spec, when duration is omitted the preceding `0x15` is also omitted, so the block format becomes `+Onset\x14Text\x14...\x14\x00`. The current code never encounters a `0x15` in this case, leaving the entire block (onset + `0x14` + text bytes) as a single part, which then fails `float()` parsing.

The fix parenthesizes the `except` clauses and rewrites `_parse_tal_block()` to first split on `0x14` to isolate the onset+duration portion, then check for `0x15` within that portion to separate onset from duration.

## Glossary

- **Bug_Condition (C)**: The conditions that trigger the two bugs — (1) importing the package with Python 2-style except syntax, or (2) parsing a TAL block where duration is absent (no `0x15` byte present)
- **Property (P)**: Correct behavior — (1) clean import, (2) correct parsing of onset, duration=None, and annotation texts from duration-less TAL blocks
- **Preservation**: Existing behavior that must remain unchanged — TAL blocks with duration present, onset validation, header date/time parsing, text extraction
- **TAL**: Time-stamped Annotations List — the on-disk format for annotations in EDF+ files
- **`_parse_tal_block()`**: The function in `src/edfplus/_tal.py` that decodes a single TAL block into (onset, duration, texts)
- **`_parse_onset()`**: The function in `src/edfplus/_tal.py` that validates and converts an onset string to float
- **`0x15`**: The byte separator between onset and duration within a TAL block (absent when duration is absent)
- **`0x14`**: The byte separator/terminator for annotation text strings within a TAL block
- **Time-keeping TAL**: The first TAL in every data record; carries onset only with empty text section (e.g. `+0\x14\x14\x00`)

## Bug Details

### Bug Condition

The bug manifests in two independent scenarios:

1. **Import failure**: Any attempt to import `edfplus` triggers a `SyntaxError` because `except ValueError, OverflowError:` is Python 2 syntax that Python 3 does not accept.
2. **TAL parsing failure**: When a TAL block has no duration (and therefore no `0x15` byte), the parser's strategy of splitting on `0x15` first produces only a single part containing the entire block. The onset portion then includes `0x14` bytes and text content, causing `float()` to fail.

**Formal Specification:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type (ImportAttempt | TALBlock)
  OUTPUT: boolean

  IF input is ImportAttempt:
    RETURN True  -- always fails due to SyntaxError

  IF input is TALBlock:
    RETURN input.block does NOT contain byte 0x15
           AND input.block contains byte 0x14
           -- i.e., duration is absent per EDF+ spec
END FUNCTION
```

### Examples

- **Import failure**: `import edfplus` raises `SyntaxError: multiple exception types must be parenthesized` at `_tal.py` line 187
- **Time-keeping TAL without duration**: `+0\x14\x14\x00` — onset is `+0`, no duration, empty text. Current code: `float("+0\x14\x14")` raises `ValueError`. Expected: onset=0.0, duration=None, texts=[]
- **Annotation TAL without duration**: `+1.5\x14Sleep stage W\x14\x00` — onset is `+1.5`, no duration, text is "Sleep stage W". Current code: `float("+1.5\x14Sleep stage W\x14")` raises `ValueError`. Expected: onset=1.5, duration=None, texts=["Sleep stage W"]
- **TAL with duration (unaffected)**: `+567\x1542.0\x14Apnea\x14\x00` — contains `0x15`, so current split-on-0x15 logic already works. Expected: onset=567.0, duration=42.0, texts=["Apnea"]

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- TAL blocks with duration present (containing `0x15`) must continue to parse correctly: onset, duration, and texts all extracted properly
- Time-keeping TALs with duration must continue to return onset as `timekeeping_onset` and be excluded from annotation list
- `_parse_onset()` must continue to validate onset range `[-999999.999, +999999.999]` and raise `ValueError` for out-of-range or non-numeric values
- Header date/time parsing in `_header.py` must continue to work for valid date strings and raise `ValueError` for invalid ones
- Text section parsing (`_parse_texts()`) must continue to split on `0x14`, discard empty strings, and decode ASCII

**Scope:**
All inputs that do NOT involve (1) the `except` syntax or (2) duration-absent TAL blocks should be completely unaffected by this fix. This includes:
- TAL blocks with duration present (onset `0x15` duration `0x14` text...)
- Mouse/keyboard interactions with files (N/A — library code)
- All header parsing beyond the two affected `except` lines
- Signal data reading and scaling

## Hypothesized Root Cause

Based on the bug description, the confirmed issues are:

1. **Python 2 `except` syntax**: The developer used `except ValueError, OverflowError:` which in Python 3 means "catch `ValueError` and bind it to variable named `OverflowError`" — but it actually raises a `SyntaxError` because the syntax is fully invalid in modern Python. The fix is trivial: parenthesize to `except (ValueError, OverflowError):`.

2. **Incorrect parsing order in `_parse_tal_block()`**: The function splits on `0x15` first, assuming every TAL block contains at least one `0x15`. Per the EDF+ spec: *"`0x15` separates onset from duration; duration is optional (if omitted, the preceding `0x15` is also omitted)."* The correct TAL format is:
   - With duration: `+Onset 0x15 Duration 0x14 Text1 0x14 ... 0x14 0x00`
   - Without duration: `+Onset 0x14 Text1 0x14 ... 0x14 0x00`

   The correct approach is to first split on the first `0x14` to isolate the onset+duration token from the text section, then within the onset+duration token check for `0x15` to separate onset from duration.

3. **No other root causes suspected**: The `_parse_texts()` function and overall `parse_tals()` orchestration logic are correct once `_parse_tal_block()` returns proper values.

## Correctness Properties

Property 1: Bug Condition - TAL Blocks Without Duration Parse Correctly

_For any_ TAL block where the duration is absent (no `0x15` byte present, block format is `+Onset\x14[Text\x14...]\x00`), the fixed `_parse_tal_block` function SHALL correctly parse the onset as a float, set duration to `None`, and extract all `0x14`-delimited text strings from the remainder of the block.

**Validates: Requirements 2.2, 2.3**

Property 2: Preservation - TAL Blocks With Duration Continue To Parse Correctly

_For any_ TAL block where the duration IS present (block contains `0x15`, format is `+Onset\x15Duration\x14[Text\x14...]\x00`), the fixed `_parse_tal_block` function SHALL produce the same result as the original function would have produced, preserving correct extraction of onset, duration, and annotation texts.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4**

## Fix Implementation

### Changes Required

**File**: `src/edfplus/_tal.py`

**Function**: `_parse_onset`

**Specific Changes**:
1. **Fix except syntax (line 229)**: Change `except ValueError, OverflowError:` to `except (ValueError, OverflowError):`

**Function**: `_parse_tal_block`

**Specific Changes**:
2. **Rewrite parsing logic**: Instead of splitting on `0x15` first, use this algorithm:
   - Split the block on the first `0x14` byte to separate the onset+duration token from the text section
   - Within the onset+duration token, check if `0x15` is present:
     - If yes: split on `0x15` — first part is onset, second part is duration
     - If no: the entire token is the onset, duration is `None`
   - The text section (everything after the first `0x14`) is then split on `0x14` to get individual text strings

3. **Update comments**: Reflect the corrected understanding of the TAL format in the docstring and inline comments

---

**File**: `src/edfplus/_header.py`

**Function**: `_parse_start_date` (line 319)

**Specific Changes**:
4. **Fix except syntax**: Change `except ValueError, AttributeError:` to `except (ValueError, AttributeError):`

**Function**: `_parse_start_time` (line 335)

**Specific Changes**:
5. **Fix except syntax**: Change `except ValueError, AttributeError:` to `except (ValueError, AttributeError):`

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that construct TAL blocks in both formats (with and without duration) and attempt to parse them. Run these tests on the UNFIXED code to observe failures and confirm the root cause.

**Test Cases**:
1. **Import Test**: Attempt to import `edfplus` (will fail with SyntaxError on unfixed code)
2. **Time-keeping TAL without duration**: Parse `+0\x14\x14\x00` (will fail with ValueError on unfixed code)
3. **Annotation TAL without duration**: Parse `+1.5\x14Sleep stage W\x14\x00` (will fail with ValueError on unfixed code)
4. **Multiple annotations without duration**: Parse `+2.0\x14Event A\x14Event B\x14\x00` (will fail on unfixed code)

**Expected Counterexamples**:
- `SyntaxError` on import due to unparenthesized except clause
- `ValueError` from `float()` when onset string contains `0x14` bytes
- Possible cause confirmed: splitting on `0x15` when `0x15` is absent leaves `0x14` bytes in the onset token

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed function produces the expected behavior.

**Pseudocode:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := _parse_tal_block_fixed(input)
  ASSERT result.onset == expected_float_onset
  ASSERT result.duration IS None
  ASSERT result.texts == expected_text_list
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT _parse_tal_block_fixed(input) == _parse_tal_block_original(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many random TAL blocks with duration present and verifies parsing consistency
- It catches edge cases in onset/duration number formatting that manual tests might miss
- It provides strong guarantees that behavior is unchanged for all TAL blocks that contain `0x15`

**Test Plan**: Observe behavior on UNFIXED code first for TAL blocks with duration, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Duration-present TAL preservation**: Verify `+567\x1542.0\x14Apnea\x14\x00` continues to parse as (567.0, 42.0, ["Apnea"])
2. **Time-keeping with duration preservation**: Verify `+123.456\x15\x14\x14\x00` continues to parse correctly
3. **Multi-text with duration preservation**: Verify `+10\x155.0\x14Text A\x14Text B\x14\x00` parses to (10.0, 5.0, ["Text A", "Text B"])
4. **Header date parsing preservation**: Verify valid dates like "01.02.85" continue to parse correctly after except syntax fix

### Unit Tests

- Test `_parse_tal_block` with duration-absent blocks (various onset values, single/multiple texts, empty texts)
- Test `_parse_tal_block` with duration-present blocks (confirm no regression)
- Test `_parse_onset` with valid and invalid onset strings (confirm except clause catches both ValueError and OverflowError)
- Test header date/time parsing with valid and invalid inputs (confirm except clause works)
- Test edge cases: empty block, block with only onset and no text, negative onsets

### Property-Based Tests

- Generate random valid onset floats in [-999999.999, +999999.999] and optional duration floats, build TAL blocks both with and without duration, verify round-trip parsing correctness
- Generate random text strings (ASCII, no control characters) and verify text section extraction works identically for duration-present blocks before and after fix
- Generate random invalid onset strings and verify ValueError is raised consistently

### Integration Tests

- Parse real EDF+ files (PSG1.edf, ST7011J0-PSG.edf) end-to-end and verify annotations are extracted
- Verify `timekeeping_onset` values are correct across all data records
- Verify annotation counts and content match expected values from known test files
