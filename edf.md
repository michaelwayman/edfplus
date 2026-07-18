# EDF / EDF+ Format Specification Summary

Condensed reference for implementing an EDF/EDF+ reader. Source specs:

- https://www.edfplus.info/specs/edf.html
- https://www.edfplus.info/specs/edfplus.html
- https://www.edfplus.info/specs/edffloat.html
- https://www.edfplus.info/specs/edftexts.html

## 1. File Layout

A file = header record + N data records.

Header size = `256 + ns * 256` bytes, where `ns` = number of signals (including the
"EDF Annotations" signal, if present). All header fields are ASCII, left-justified,
space-padded. Samples are 2-byte little-endian 2's-complement integers.

### Header record (256 bytes)

| Field                          | Bytes | Notes                                                  |
|--------------------------------|-------|--------------------------------------------------------|
| version                        | 8     | always `"0"` (padded)                                  |
| local patient identification   | 80    | see below                                              |
| local recording identification | 80    | see below                                              |
| start date                     | 8     | `dd.mm.yy`                                             |
| start time                     | 8     | `hh.mm.ss`                                             |
| number of bytes in header      | 8     | `256 + ns*256`                                         |
| reserved                       | 44    | `"EDF+C"` / `"EDF+D"` / blank (plain EDF)              |
| number of data records         | 8     | `-1` if unknown while recording                        |
| duration of a data record      | 8     | seconds; may be `0` (annotation-only/degenerate files) |
| number of signals (ns)         | 4     |                                                        |

### Per-signal header (`ns` blocks of 256 bytes, fields grouped by column not interleaved)

| Field              | Bytes | Notes                                                                   |
|--------------------|-------|-------------------------------------------------------------------------|
| label              | 16    | e.g. `"EEG Fpz-Cz"`; `"EDF Annotations"` is reserved                    |
| transducer type    | 80    |                                                                         |
| physical dimension | 8     | e.g. `"uV"`; `"Filtered"` triggers log transform (edffloat)             |
| physical minimum   | 8     |                                                                         |
| physical maximum   | 8     |                                                                         |
| digital minimum    | 8     |                                                                         |
| digital maximum    | 8     |                                                                         |
| prefiltering       | 80    | e.g. `"HP:0.1Hz LP:75Hz"`; encodes log-transform params when applicable |
| samples per record | 8     | sample rate = this / record duration                                    |
| reserved           | 32    |                                                                         |

### Data records

Each record stores, in signal order, all samples for signal 1, then all samples for
signal 2, etc. Sample count per signal per record = that signal's "samples per record".

**Scaling (linear):**
`physical = physical_min + (digital - digital_min) * (physical_max - physical_min) / (digital_max - digital_min)`

**Deriving record count when declared as -1:**
`num_records = (file_size - header_bytes) / bytes_per_record`, where
`bytes_per_record = sum(samples_per_record_i * 2)` over all signals.

## 2. EDF+ Additions

- **Reserved field** must start with `"EDF+C"` (continuous) or `"EDF+D"` (discontinuous —
  data records need not be contiguous in time). This is the *only* real incompatibility
  with plain EDF — old EDF readers still parse EDF+ files fine, just without knowing
  about discontinuity.
- **Local patient identification** (80 bytes), space-separated subfields: hospital code,
  sex (`F`/`M`/`X`), birthdate `dd-MMM-yyyy` (English month abbreviation), patient name.
  Unknown fields = `"X"`; spaces inside a subfield become `_`.
  Example: `MCH-0234567 F 02-MAY-1951 Haagse_Harry`
- **Local recording identification** (80 bytes): literal `"Startdate"`, startdate
  `dd-MMM-yyyy`, investigation code, investigator code, equipment code.
  Example: `Startdate 02-MAR-2002 PSG-1234/2002 NN Telemetry03`
- **Mandatory "EDF Annotations" signal**: digital min/max fixed at `-32768`/`32767`;
  physical min/max just need to differ; other signal-header fields blank. Its
  "samples per record" * 2 bytes hold packed TAL (Time-stamped Annotations List) data —
  raw characters, not encoded integers.
- **TAL structure**: `+Onset[0x15]Duration[0x14]Text1[0x14]Text2[0x14]...[0x14][0x00]`
    - Onset: starts with `+`/`-`, digits and `.` only; required.
    - `0x15` separates onset from duration; duration is optional (if omitted, the
      preceding `0x15` is also omitted).
    - `0x14` separates/terminates each annotation text.
    - `0x00` terminates the TAL; a TAL may not span a data-record boundary; unused
      trailing bytes in the record are `0x00`-padded.
- **Time-keeping annotation**: the *first* annotation of the *first* "EDF Annotations"
  signal instance in every data record has empty text; its onset = seconds since file
  start that this record begins, e.g. `+567[0x14][0x14]`. First record's is always
  `+0.X[0x14][0x14]` (`.X` omitted if 0). This is required to get correct absolute
  timestamps, especially for EDF+D.
- **Number of data records** may be `-1` only while a recording is still open; must be
  correct once the file is closed/finalized.

## 3. Logarithmic Transform (edffloat)

Used when a signal's regular ±32767 int16 range can't cover its dynamic range linearly
(e.g. very large dynamic-range physiological values). Applies per-signal when:

- **Physical dimension field** = literally `"Filtered"`.
- **physical_maximum = digital_maximum = 32767**; **physical_minimum = digital_minimum = -32767**
  (note: `-32767`, not `-32768`).
- **Prefiltering field** encodes the transform as:
  `sign*LN[sign*(<physical dimension>)/(Ymin)]/(a)`
  e.g. `sign*LN[sign*(uV      )/(0.01    )]/(0.002   )` — 8-char space-padded subfields
  give the real physical dimension, `Ymin`, and `a`.

**Digital → physical:**

- `N > 0` → `Y = Ymin * EXP(a * N)`
- `N == 0` → `Y = 0`
- `N < 0` → `Y = -Ymin * EXP(-a * N)`

**Physical → digital** (inverse, for a future write path):

- `Y > Ymin` → `N = round(LN(Y / Ymin) / a)`
- `|Y| <= Ymin` → `N = 0`
- `Y < -Ymin` → `N = -round(LN(-Y / Ymin) / a)`

`a` sets relative accuracy (e.g. `a=0.005` ≈ 0.5% per step); `Ymin` sets the zero-centered
deadband and the bottom of the dynamic range.

## 4. Standard Texts & Conventions (edftexts)

Recommendations only, not load-bearing for parsing correctness:

- **Label** = `"<signal type> <sensor>"`, e.g. `"EEG Fpz-Cz"`.
- **Physical dimension** = `"<SI prefix><unit>"`, e.g. `"uV"`.
- Standard 10/20 & 10/10% EEG electrode names (Fp1, Fpz, Fp2, F3, Fz, F4, C3, Cz, C4,
  P3, Pz, P4, O1, Oz, O2, A1, A2, plus intermediate positions).
- Standard respiration labels: `chest, abdomen, oral, nasal, oro-nasal`.
- Standard PSG annotation vocabulary: sleep stages, respiratory events (apnea types,
  hypopnea, RERA, desaturation), limb movements (PLMS), arousal, cardiac events,
  bruxism, RBD/RMD.
