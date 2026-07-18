# Requirements Document

## Introduction

This feature adds an EDF/EDF+ file reader to the `edfplus` Python library. The reader
parses binary EDF (European Data Format) and EDF+ files, exposes structured header
metadata, and returns physical signal samples scaled from raw digital integers. It
supports plain EDF, EDF+C (continuous), and EDF+D (discontinuous) variants, as well as
the logarithmic-transform (edffloat) encoding and the EDF+ annotation channel (TALs).

## Glossary

- **EDF_Reader**: The top-level component that accepts a file path or file-like object
  and returns a parsed `EDFFile`.
- **Header_Parser**: The component responsible for reading and decoding the 256-byte
  global header and the per-signal header blocks.
- **Signal_Parser**: The component responsible for reading raw data records and
  converting 2-byte little-endian integers into digital sample arrays.
- **Scaler**: The component that applies the linear or logarithmic transform to convert
  digital samples to physical values.
- **TAL_Parser**: The component that extracts Time-stamped Annotation Lists from EDF+
  Annotations signal data.
- **EDFFile**: The top-level data structure returned by the EDF_Reader, containing
  header metadata, signals, and (for EDF+) annotations.
- **EDFHeader**: A data structure holding the global header fields (version, patient
  info, recording info, start date/time, number of data records, record duration).
- **SignalHeader**: A data structure holding per-signal header fields (label, transducer
  type, physical dimension, physical min/max, digital min/max, prefiltering, samples per
  record).
- **Signal**: A data structure holding a SignalHeader, the physical sample array, and
  the sample rate.
- **Annotation**: A data structure holding onset (seconds from file start), duration
  (optional), and one or more annotation text strings.
- **TAL**: A Time-stamped Annotations List entry; one or more Annotations packed into a
  single null-terminated block.
- **Data_Record**: A fixed-length binary block in the EDF file containing one record's
  worth of samples for every signal in interleaved-by-signal order.
- **edffloat**: The logarithmic scaling extension applied when a signal's physical
  dimension field is `"Filtered"` and its prefiltering field encodes log-transform
  parameters.
- **Physical_Value**: A floating-point sample value expressed in the signal's physical
  unit (e.g. µV).
- **Digital_Value**: A raw 16-bit signed integer sample as stored in the file.

---

## Requirements

### Requirement 1: Open and Validate EDF Files

**User Story:** As a researcher, I want to open an EDF or EDF+ file by path, so that I
can access its contents without manually handling binary parsing.

#### Acceptance Criteria

1. WHEN a valid file path pointing to an EDF or EDF+ file is provided, THE EDF_Reader
   SHALL return an EDFFile object containing the parsed header fields and signal
   metadata for all channels in the file.
2. WHEN the file path does not exist, THE EDF_Reader SHALL raise a `FileNotFoundError`
   with the path included in the error message.
3. WHEN the file's version field (first 8 bytes) is not `"0       "`, THE EDF_Reader
   SHALL raise a `ValueError` whose message includes both the found version value and
   an indication that the version is unsupported.
4. WHEN the declared header byte count does not equal `256 + ns * 256` (where `ns` is
   the number of signals read from the header), THE EDF_Reader SHALL raise a
   `ValueError` indicating a malformed header.
5. WHEN the file is shorter than the declared header size, THE EDF_Reader SHALL raise a
   `ValueError` indicating a truncated header.
6. WHEN the file exists but the process does not have read permission, THE EDF_Reader
   SHALL raise a `PermissionError` with the path included in the error message.
7. WHEN any numeric header field (such as `ns` or `number of data records`) cannot be
   parsed as an integer, THE EDF_Reader SHALL raise a `ValueError` identifying the
   offending field name and its raw value.

---

### Requirement 2: Parse the Global Header

**User Story:** As a researcher, I want structured access to the global file header
fields, so that I can inspect recording metadata without reading binary offsets manually.

#### Acceptance Criteria

1. THE Header_Parser SHALL decode the version, local patient identification, local
   recording identification, start date, start time, number of data records, record
   duration, and number of signals from the 256-byte global header.
2. WHEN the `reserved` field starts with `"EDF+C"`, THE Header_Parser SHALL set the
   EDFHeader variant to `EDF+C`.
3. WHEN the `reserved` field starts with `"EDF+D"`, THE Header_Parser SHALL set the
   EDFHeader variant to `EDF+D`.
4. WHEN the `reserved` field is blank (all spaces or empty after stripping), THE
   Header_Parser SHALL set the EDFHeader variant to `EDF`.
5. WHEN the `reserved` field is non-blank and does not start with `"EDF+C"` or
   `"EDF+D"`, THE Header_Parser SHALL raise a `ValueError` identifying the unrecognized
   reserved field value.
6. IF the `number of data records` field equals `-1`, THEN THE Header_Parser SHALL
   compute the actual record count as
   `(file_size - header_bytes) / bytes_per_record`, where `bytes_per_record` is the
   sum of `samples_per_record * 2` over all signals.
7. THE Header_Parser SHALL expose the recording start as three separate attributes on
   `EDFHeader`:
   - `start_date`: a Python `date` object parsed from the `dd.mm.yy` field,
     interpreting two-digit years as `19xx` when `yy >= 85` and as `20xx` when
     `yy < 85`.
   - `start_time`: a Python `time` object parsed from the `hh.mm.ss` field
     (timezone-naive by default).
   - `start_datetime`: a Python `datetime` object combining `start_date` and
     `start_time` (timezone-naive by default).
8. WHEN the global header buffer is shorter than 256 bytes, or when any numeric field
   in the global header (such as `number of data records` or `record duration`) cannot
   be parsed as its expected numeric type, THE Header_Parser SHALL raise a `ValueError`
   and SHALL NOT return a partially-populated EDFHeader.
9. WHEN `read_edf` is called with a `tzinfo` argument (a `datetime.tzinfo` instance,
   default `None`), THE Header_Parser SHALL attach that tzinfo to the `start_datetime`
   `datetime` object and to the `start_time` `time` object using
   `datetime.replace(tzinfo=tzinfo)` and `time.replace(tzinfo=tzinfo)` respectively.
   The `start_date` SHALL remain a plain `date` object unaffected by the `tzinfo`
   argument.
10. WHEN `tzinfo` is `None` (the default), THE Header_Parser SHALL produce
    timezone-naive `start_datetime` and `start_time` objects (i.e. `.tzinfo` is
    `None`).
11. WHEN a `tzinfo` value is provided that is not a `datetime.tzinfo` instance, THE
    EDF_Reader SHALL raise a `TypeError` identifying the argument name and the received
    type.

---

### Requirement 3: Parse Per-Signal Headers

**User Story:** As a researcher, I want structured access to each signal's header
fields, so that I can understand channel properties (units, calibration, sample rate).

#### Acceptance Criteria

1. THE Header_Parser SHALL decode, for every signal, the label, transducer type,
   physical dimension, physical minimum, physical maximum, digital minimum, digital
   maximum, prefiltering, and samples-per-record fields.
2. THE Header_Parser SHALL compute each signal's sample rate as
   `samples_per_record / record_duration` and store it in the SignalHeader.
3. WHEN `record_duration` is `0`, THE Header_Parser SHALL set the sample rate to `0`
   rather than raising a division error.
4. THE Header_Parser SHALL strip leading and trailing whitespace from all ASCII
   string-typed header fields (label, transducer type, physical dimension,
   prefiltering).
5. WHEN a signal's label is `"EDF Annotations"` (after stripping), THE Header_Parser
   SHALL mark that signal as the Annotations channel, store its SignalHeader
   separately, and exclude it from the regular Signal list so it does not appear in
   `EDFFile.signals`.
6. WHEN any numeric per-signal header field (physical minimum, physical maximum,
   digital minimum, digital maximum, or samples-per-record) cannot be parsed as its
   expected numeric type, THE Header_Parser SHALL raise a `ValueError` identifying the
   signal index (0-based), the field name, and the raw field value.
7. THE `Signal` object SHALL expose all fields from its `SignalHeader` as direct
   read-only properties, specifically: `label` (str), `transducer_type` (str),
   `physical_dimension` (str), `physical_min` (float), `physical_max` (float),
   `digital_min` (int), `digital_max` (int), `prefiltering` (str), and
   `samples_per_record` (int).

---

### Requirement 4: Read and Scale Signal Data

**User Story:** As a researcher, I want each signal's samples returned as a NumPy array
of physical values by default, with the option to retrieve raw digital (int16) values
without scaling, to choose a smaller float dtype for physical values to reduce memory
footprint, and to obtain per-sample onset and datetime timestamp arrays, so that I can
immediately perform analysis or accurately correlate samples to real-world time.

#### Acceptance Criteria

1. THE Signal_Parser SHALL read each Data_Record in file order and concatenate
   per-signal samples into a single contiguous array of Digital_Values for each signal.
2. THE Scaler SHALL convert Digital_Values to Physical_Values using the formula:
   `physical = physical_min + (digital - digital_min) * (physical_max - physical_min) / (digital_max - digital_min)`
3. THE Scaler SHALL store Physical_Values in a `numpy.ndarray` with dtype `float64` by
   default, using a C-contiguous memory layout.
4. WHEN `digital_max == digital_min`, THE Scaler SHALL return an array filled with
   `physical_min` rather than raising a division error.
5. THE EDFFile SHALL expose each Signal by its exact stripped label string (as returned
   by `SignalHeader.label`) and by 0-based integer index in file signal order,
   excluding the EDF Annotations channel.
6. WHEN an integer index is out of range or a label string does not match any signal,
   THE EDFFile SHALL raise an `IndexError` (for integer access) or `KeyError` (for
   label access) respectively.
7. WHEN scaling is disabled (the caller requests digital values), THE Signal_Parser
   SHALL return the raw Digital_Values as a `numpy.ndarray` with dtype `int16` without
   applying the linear or logarithmic transform.
8. WHEN scaling is enabled and the caller provides a float dtype (such as `float32`),
   THE Scaler SHALL cast the Physical_Values array to that dtype rather than `float64`.
9. IF scaling is disabled and the caller also provides a float dtype, THEN THE Scaler
   SHALL raise a `ValueError` indicating that a float dtype cannot be combined with
   digital (unscaled) output.
10. THE `Signal` SHALL expose a `timestamps()` method that returns a `numpy.ndarray` of
    `float64` values representing the onset in seconds from the start of the recording
    for each sample in `Signal.samples`. For sample index `i`, the onset SHALL be
    computed as `i / sample_rate`. For EDF+D signals, NaN-padded gap samples SHALL have
    a corresponding NaN value in the timestamps array so that the two arrays remain
    positionally aligned.
11. THE `Signal` SHALL expose a `datetimes()` method that returns a `numpy.ndarray` of
    `numpy.datetime64` values representing the absolute UTC (or timezone-aware if
    `tzinfo` was provided) datetime for each sample. Each element SHALL be computed as
    `EDFHeader.start_datetime + timedelta(seconds=onset_i)` for each onset from
    `timestamps()`. Gap samples (NaN onset) SHALL produce `numpy.datetime64('NaT')`
    entries.

---

### Requirement 5: Logarithmic (edffloat) Scaling

**User Story:** As a researcher, I want signals that use the edffloat logarithmic
encoding to be transparently decoded into physical values, so that I can work with
high-dynamic-range signals without knowing about the encoding.

#### Acceptance Criteria

1. IF a signal's physical dimension field equals `"Filtered"` and its physical maximum
   equals `32767` and its digital maximum equals `32767`, THEN THE Scaler SHALL apply
   the logarithmic transform in place of the linear transform for that signal.
2. WHILE applying the logarithmic transform to a signal, IF the prefiltering field
   matches the pattern `sign*LN[sign*(<dim>)/(<Ymin>)]/(<a>)`, THEN THE Scaler SHALL
   parse numeric values for `Ymin` and `a` from the prefiltering field.
3. IF the logarithmic transform is applied and the digital value `N > 0`, THEN THE
   Scaler SHALL produce `Y = Ymin * exp(a * N)`.
4. IF the logarithmic transform is applied and the digital value `N == 0`, THEN THE
   Scaler SHALL produce `Y = 0`.
5. IF the logarithmic transform is applied and the digital value `N < 0`, THEN THE
   Scaler SHALL produce `Y = -Ymin * exp(-a * N)`.
6. IF the prefiltering field cannot be parsed as a valid edffloat descriptor, or if
   the parsed value of `Ymin` is less than or equal to `0`, or if the parsed value of
   `a` is less than or equal to `0`, THEN THE Scaler SHALL raise a `ValueError`
   identifying the offending signal label.

---

### Requirement 6: Parse EDF+ Patient and Recording Identification

**User Story:** As a researcher, I want structured access to the EDF+ patient and
recording subfields, so that I can retrieve patient demographics and recording provenance
without manually splitting space-delimited strings.

#### Acceptance Criteria

1. WHEN the EDFHeader variant is `EDF+C` or `EDF+D`, THE Header_Parser SHALL parse
   the local patient identification field into four positional subfields in order:
   hospital code, sex, birthdate, and patient name.
2. WHEN a subfield value is `"X"`, THE Header_Parser SHALL represent that subfield as
   `None` to indicate the value is unknown.
3. WHEN the local patient identification birthdate subfield is present and not `"X"`,
   THE Header_Parser SHALL parse it as a Python `date` object from the `dd-MMM-yyyy`
   format, where `MMM` is one of the English three-letter month abbreviations
   (Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep, Oct, Nov, Dec).
4. WHEN the local patient identification birthdate subfield is present, not `"X"`, and
   cannot be parsed as a valid `dd-MMM-yyyy` date, THE Header_Parser SHALL raise a
   `ValueError` identifying the field as `local patient identification birthdate` and
   including the raw subfield value.
5. WHEN the EDFHeader variant is `EDF+C` or `EDF+D`, THE Header_Parser SHALL parse
   the local recording identification field into four positional subfields in order:
   startdate, investigation code, investigator code, and equipment code.
6. WHEN the local recording identification startdate subfield is present and not `"X"`,
   THE Header_Parser SHALL parse it as a Python `date` object from the `dd-MMM-yyyy`
   format using the same English month abbreviations as criterion 3.
7. WHEN the local recording identification startdate subfield is present, not `"X"`,
   and cannot be parsed as a valid `dd-MMM-yyyy` date, THE Header_Parser SHALL raise a
   `ValueError` identifying the field as `local recording identification startdate` and
   including the raw subfield value.
8. WHEN underscores appear within a subfield value that is not represented as `None`,
   THE Header_Parser SHALL replace each underscore with a space when returning the
   value.

---

### Requirement 7: Parse EDF+ Annotations (TALs)

**User Story:** As a researcher, I want to access clinical annotations embedded in an
EDF+ file, so that I can correlate events (e.g. sleep stages, apneas) with signal data.

#### Acceptance Criteria

1. WHEN the EDFHeader variant is `EDF+C` or `EDF+D`, THE TAL_Parser SHALL extract all
   TAL entries from the signal whose header label equals `"EDF Annotations"` across
   all Data_Records.
2. THE TAL_Parser SHALL parse each TAL entry into an Annotation with onset (seconds as
   `float` decoded from its ASCII decimal representation in the TAL byte stream),
   optional duration (`float` decoded from its ASCII decimal representation, or `None`
   if absent), and a list of one or more annotation text strings.
3. WHEN an annotation text string is empty, THE TAL_Parser SHALL omit it from the
   annotation's text list, so that time-keeping annotations with empty text are
   excluded from the returned Annotation list.
4. THE EDFFile SHALL expose parsed annotations as a list of Annotation objects ordered
   in ascending onset time order.
5. WHEN a TAL block contains a time-keeping annotation (onset matches the record start
   to within 0.001 seconds and its text list is empty after applying criterion 3), THE
   TAL_Parser SHALL use that onset to establish the absolute start time for the
   enclosing Data_Record but SHALL NOT include it in the public annotation list.
6. WHEN a TAL entry's onset field cannot be parsed as a decimal number, or when the
   parsed onset value is outside the range −999999.999 to +999999.999 seconds, THE
   TAL_Parser SHALL raise a `ValueError` identifying the offending record index and
   raw onset bytes, and SHALL NOT return a partially-built annotation list.
7. WHEN the EDF Annotations signal data for any Data_Record is shorter than the
   sample count declared in the signal header, THE TAL_Parser SHALL raise a
   `ValueError` identifying the record index and the shortfall in bytes.

---

### Requirement 8: EDF+D Discontinuous Record Timing

**User Story:** As a researcher, I want correct absolute timestamps for each signal
sample in a discontinuous EDF+D recording, so that gaps in recording are accurately
represented.

#### Acceptance Criteria

1. WHEN the EDFHeader variant is `EDF+D`, THE Signal_Parser SHALL read the
   time-keeping TAL (a TAL with a numeric onset and zero-duration at the start of the
   annotation channel) from each Data_Record to determine the absolute onset of that
   record before placing its samples.
2. WHEN a gap exists between consecutive Data_Records in an EDF+D file (i.e. the
   time-keeping TAL onset of the next record is greater than
   `previous_onset + record_duration`), THE EDFFile SHALL insert
   `floor(gap_duration * sample_frequency)` `NaN` values into each signal array for
   the missing interval, where `gap_duration = next_onset - (previous_onset + record_duration)`
   and `sample_frequency` is the per-signal sample rate.
3. WHEN the EDFHeader variant is `EDF+C`, THE Signal_Parser SHALL compute each
   record's onset as `record_index * record_duration` without reading time-keeping TALs.
4. WHEN the EDFHeader variant is `EDF+D` and a Data_Record's annotation channel
   contains no time-keeping TAL, THE Signal_Parser SHALL raise a `ValueError`
   identifying the record index and SHALL NOT place any samples from that record.
5. WHEN the EDFHeader variant is `EDF+D` and the time-keeping TAL onset of a
   Data_Record is less than `previous_onset + record_duration` (i.e. records overlap),
   THE Signal_Parser SHALL raise a `ValueError` identifying both the offending record
   index and the overlap duration, and SHALL NOT place any samples from that record.

---

### Requirement 9: EDF File Representation Round-Trip

**User Story:** As a developer, I want to verify that parsing an EDF file and
re-serialising its header fields produces the original byte sequence, so that the
parser is not lossy.

#### Acceptance Criteria

1. THE Header_Parser SHALL preserve all raw ASCII bytes for every global header field
   such that round-tripping (parse then format) reproduces the original 256-byte header
   block exactly.
2. THE Header_Parser SHALL preserve all raw ASCII bytes for every per-signal header
   field such that round-tripping (parse then format) reproduces the original
   `ns * 256`-byte per-signal header block exactly.
3. FOR ALL valid EDF files, parsing the header then formatting the header SHALL produce
   byte-for-byte identical output to the original header bytes (round-trip property).

---

### Requirement 10: Public API

**User Story:** As a developer, I want a simple, idiomatic Python API for reading EDF
files, so that I can integrate the library into my analysis code with minimal boilerplate.

#### Acceptance Criteria

1. THE EDF_Reader SHALL be importable as `from edfplus import read_edf`.
2. WHEN `read_edf(path)` is called with a `str` or `pathlib.Path`, THE EDF_Reader SHALL
   return an `EDFFile` instance.
3. WHEN `read_edf(file_obj)` is called with a binary file-like object that exposes both
   `.read()` and `.seek()` methods, THE EDF_Reader SHALL return an `EDFFile` instance.
4. THE EDFFile SHALL expose a `signals` property returning a list of `Signal` objects
   (one per non-annotation channel) in the order they appear in the file. Each `Signal`
   object in this list SHALL contain only the header metadata for that channel; sample
   data SHALL NOT be loaded until explicitly requested via `read_signals()` or a
   sample-access method on the `Signal`.
5. THE EDFFile SHALL expose an `annotations` property returning a list of `Annotation`
   objects; for files that are not EDF+C or EDF+D (i.e. have no EDF Annotations
   signal), this list SHALL be empty.
6. THE EDFFile SHALL expose a `header` property returning the `EDFHeader` object.
7. THE Signal SHALL expose a `samples` property returning a `numpy.ndarray` of
   `float64` physical values scaled from Digital_Values using the four header
   calibration fields (`physical_min`, `physical_max`, `digital_min`, `digital_max`).
8. THE Signal SHALL expose a `label` property returning the signal label string with
   all leading and trailing ASCII space characters (0x20) removed.
9. THE Signal SHALL expose a `sample_rate` property returning the signal's sample rate
   as a `float` computed as `samples_per_record / record_duration`; the value SHALL
   be `> 0.0` when `record_duration > 0`.
10. WHEN `read_edf` is called with a path that does not exist, a path that is
    unreadable, or a file with a structurally invalid header, THE EDF_Reader SHALL
    raise the appropriate exception (`FileNotFoundError`, `PermissionError`, or
    `ValueError`) without returning a partially-constructed EDFFile.
11. WHEN `read_edf` is called with a file-like object that does not expose `.read()` or
    `.seek()`, THE EDF_Reader SHALL raise a `TypeError` identifying which method is
    missing.
12. THE `read_edf` function SHALL accept a `physical` keyword argument (default `True`);
    WHEN `physical=False` is passed, THE EDF_Reader SHALL return signals whose `samples`
    array contains raw Digital_Values as `int16` without scaling.
13. THE `read_edf` function SHALL accept a `dtype` keyword argument (default `None`);
    WHEN `dtype` is provided and `physical=True`, THE Scaler SHALL cast Physical_Values
    to the specified float dtype (e.g. `numpy.float32`) before returning.
14. WHEN `dtype` is provided and `physical=False`, THE EDF_Reader SHALL raise a
    `ValueError` indicating that `dtype` cannot be combined with `physical=False`.
15. THE Signal SHALL expose a `physical_samples(dtype=None)` method that returns scaled
    Physical_Values as a `numpy.ndarray`; WHEN `dtype` is `None`, the array SHALL have
    dtype `float64`; WHEN `dtype` is provided, the array SHALL be cast to that float
    dtype.
16. THE Signal SHALL expose a `digital_samples()` method that returns raw Digital_Values
    as a `numpy.ndarray` with dtype `int16`, without applying any scaling transform.
17. THE `read_edf` function SHALL accept a `tzinfo` keyword argument (type
    `datetime.tzinfo`, default `None`); WHEN provided, it SHALL be forwarded to the
    Header_Parser so that `EDFHeader.start_datetime` and `EDFHeader.start_time` are
    timezone-aware as specified in Requirement 2 criteria 9–11.
18. THE `EDFFile` SHALL expose a `read_signals(signals: Sequence[str] | Sequence[int] = ())`
    method that reads and returns a `list[Signal]` where each `Signal` contains fully
    loaded sample data. The `signals` parameter identifies which channels to load by
    label string or by 0-based integer index; WHEN `signals` is an empty sequence
    (`()`), THE method SHALL load and return all non-annotation channels in file order.
19. WHEN `signals` contains label strings, THE `read_signals` method SHALL return the
    `Signal` objects in the same order as the labels were provided in `signals`.
20. WHEN `signals` contains integer indices, THE `read_signals` method SHALL return the
    `Signal` objects in the same order as the indices were provided in `signals`.
21. WHEN `signals` contains a label string that does not match any non-annotation
    channel, THE `read_signals` method SHALL raise a `KeyError` identifying the
    unrecognized label.
22. WHEN `signals` contains an integer index that is out of range for the
    non-annotation channel list, THE `read_signals` method SHALL raise an `IndexError`
    identifying the out-of-range index.
23. WHEN `read_signals` is called, THE Signal_Parser SHALL seek to and read only the
    data records required for the requested channels, skipping the raw bytes for
    unrequested channels, so that loading a single channel does not require reading the
    full file into memory.
