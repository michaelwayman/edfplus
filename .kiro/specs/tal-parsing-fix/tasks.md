# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** - TAL Blocks Without Duration Fail to Parse
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: Scope the property to concrete failing cases - TAL blocks without `0x15` byte (duration absent)
  - Write a property-based test in `tests/test_tal_parsing_fix.py` that:
    - Generates valid onset floats in [-999999.999, +999999.999] and optional ASCII text strings
    - Constructs TAL blocks WITHOUT duration: `+{onset}\x14[Text\x14...]\x00`
    - Calls `_parse_tal_block()` and asserts: onset parses to correct float, duration is `None`, texts are correctly extracted
  - Also include concrete cases from the design:
    - Time-keeping TAL: `+0\x14\x14\x00` → onset=0.0, duration=None, texts=[]
    - Annotation TAL: `+1.5\x14Sleep stage W\x14\x00` → onset=1.5, duration=None, texts=["Sleep stage W"]
    - Multi-annotation: `+2.0\x14Event A\x14Event B\x14\x00` → onset=2.0, duration=None, texts=["Event A", "Event B"]
  - Note: The import itself will fail with `SyntaxError` due to unparenthesized except clauses - this is part of the bug condition
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: Test FAILS (SyntaxError on import or ValueError from float parsing confirms the bug exists)
  - Document counterexamples found to understand root cause
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 1.1, 1.2, 1.3, 2.2, 2.3_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - TAL Blocks With Duration Continue To Parse Correctly
  - **IMPORTANT**: Follow observation-first methodology
  - Note: Since the unfixed code has a SyntaxError on import, preservation tests cannot run against unfixed code directly. Instead, observe the INTENDED behavior from the design document and EDF+ spec for duration-present TAL blocks, which the existing `_parse_tal_block` logic handles correctly (the bug only affects duration-absent blocks).
  - Write a property-based test in `tests/test_tal_parsing_fix.py` that:
    - Generates valid onset floats in [-999999.999, +999999.999]
    - Generates valid duration floats > 0
    - Generates lists of ASCII text strings (no control characters)
    - Constructs TAL blocks WITH duration: `+{onset}\x15{duration}\x14[Text\x14...]\x00`
    - Calls `_parse_tal_block()` and asserts: onset parses correctly, duration parses correctly, texts are correctly extracted
  - Include concrete preservation cases:
    - `+567\x1542.0\x14Apnea\x14\x00` → onset=567.0, duration=42.0, texts=["Apnea"]
    - `+123.456\x15\x14\x14\x00` → onset=123.456, duration=None or empty, texts=[] (time-keeping with duration field empty)
    - `+10\x155.0\x14Text A\x14Text B\x14\x00` → onset=10.0, duration=5.0, texts=["Text A", "Text B"]
  - Also test `_parse_onset()` preservation:
    - Valid onsets (`"+1.5"`, `"-0.25"`, `"+0"`) return correct float values
    - Invalid onsets raise `ValueError`
  - Run tests after fixing the except syntax (step 3.1a) but BEFORE rewriting `_parse_tal_block` logic
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline behavior for duration-present blocks to preserve)
  - Mark task complete when tests are written, run, and passing
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 3. Fix TAL parsing bugs

  - [x] 3.1 Fix Python 2-style except syntax
    - In `src/edfplus/_tal.py` `_parse_onset()`: change `except ValueError, OverflowError:` to `except (ValueError, OverflowError):`
    - In `src/edfplus/_header.py` `parse_global_header()`: change `except ValueError, AttributeError:` to `except (ValueError, AttributeError):` on both occurrences (lines ~217 and ~228)
    - Verify the package imports successfully after this change
    - _Bug_Condition: isBugCondition(ImportAttempt) — always True due to SyntaxError_
    - _Expected_Behavior: Package imports without SyntaxError_
    - _Requirements: 1.1, 2.1_

  - [x] 3.2 Rewrite `_parse_tal_block()` parsing logic
    - Replace the current split-on-`0x15`-first approach with the correct algorithm:
      1. Split the block on the first `0x14` byte to separate onset+duration token from text section
      2. Within the onset+duration token, check if `0x15` is present:
         - If yes: split on `0x15` — first part is onset, second part is duration
         - If no: the entire token is the onset, duration is `None`
      3. The text section (everything after the first `0x14`) is split on `0x14` to get individual text strings (discard empty strings)
    - Update docstring and inline comments to reflect the corrected parsing strategy
    - _Bug_Condition: isBugCondition(TALBlock) where block does NOT contain 0x15 AND contains 0x14_
    - _Expected_Behavior: onset=float, duration=None, texts=list of strings_
    - _Preservation: TAL blocks WITH 0x15 continue to parse identically_
    - _Requirements: 1.2, 1.3, 2.2, 2.3, 3.1, 3.2_

  - [x] 3.3 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - TAL Blocks Without Duration Parse Correctly
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.2, 2.3_

  - [x] 3.4 Verify preservation tests still pass
    - **Property 2: Preservation** - TAL Blocks With Duration Continue To Parse Correctly
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix (no regressions)
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5_

- [x] 4. Checkpoint - Ensure all tests pass
  - Run full test suite: `uv run pytest tests/`
  - Verify all integration tests pass (TestPSGIntegration with real EDF+ files)
  - Verify all property-based tests pass
  - Verify no regressions in existing test modules (`test_header.py`, `test_scaler_edffloat.py`, `test_reader.py`, `test_read_signals.py`)
  - Ensure all tests pass, ask the user if questions arise.
