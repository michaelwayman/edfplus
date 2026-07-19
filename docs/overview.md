# Overview


## `read_edf()` reference

```python
from edfplus import read_edf

edf = read_edf(
    source,                      # str, Path, or binary file-like object
    *,
    physical=True,               # Scale samples to physical units (float64)
    dtype=None,                  # Cast physical values to a specific NumPy dtype
    tzinfo=None,                 # Attach timezone info to parsed datetimes
    eager_load_samples=False,    # Load all samples immediately instead of lazily
)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | `str \| Path \| BinaryIO` | *(required)* | Path to an EDF/EDF+ file, or an open binary stream with `.read()` and `.seek()`. |
| `physical` | `bool` | `True` | When `True`, samples are scaled from raw int16 digital values to physical units using the calibration values in the header. When `False`, raw int16 values are returned. |
| `dtype` | `numpy.dtype \| type \| None` | `None` | Cast physical samples to a specific dtype (e.g., `numpy.float32` for lower memory usage). Only valid when `physical=True`. |
| `tzinfo` | `datetime.tzinfo \| None` | `None` | Timezone to apply to `start_time` and `start_datetime` on the header. `None` produces timezone-naive objects. |
| `eager_load_samples` | `bool` | `False` | When `True`, all signal samples are read into memory at open time. When `False` (default), samples are loaded lazily on first access. |

### Returns

An `EDFFile` instance. Use it as a context manager to ensure the file handle is closed:

```python
with read_edf("path/to/file.edf") as edf:
    ...
```

### Exceptions

- `FileNotFoundError` -- path does not exist
- `PermissionError` -- no read permission
- `TypeError` -- invalid source type, or invalid `tzinfo`
- `ValueError` -- `dtype` with `physical=False`, or malformed/truncated header

## Data structures

### `EDFFile`

The top-level container returned by `read_edf()`. Holds the parsed header, all signal instances, and annotations.

| Property | Type | Description |
|----------|------|-------------|
| `header` | `EDFHeader` | Parsed global header metadata. |
| `signals` | `list[Signal]` | Non-annotation signal channels (lazy-loading). |
| `annotations` | `list[Annotation]` | Parsed EDF+ annotations; empty for plain EDF. |

Supports indexing by label (`edf["EEG Fp1"]`) or integer position (`edf[0]`).

### `EDFHeader`

A frozen dataclass containing all fields from the 256-byte global header.

| Field | Type | Description |
|-------|------|-------------|
| `version` | `str` | Always `"0"` for valid EDF files. |
| `variant` | `"EDF" \| "EDF+C" \| "EDF+D"` | Detected file variant. |
| `start_date` | `datetime.date` | Recording start date. |
| `start_time` | `datetime.time` | Recording start time. |
| `start_datetime` | `datetime.datetime` | Combined date and time. |
| `num_records` | `int` | Number of data records. |
| `record_duration` | `float` | Duration of each data record (seconds). |
| `num_signals` | `int` | Total number of signals including annotation channels. |
| `header_bytes` | `int` | Total header size in bytes. |
| `local_patient_id` | `str` | Raw 80-byte patient identification field. |
| `local_recording_id` | `str` | Raw 80-byte recording identification field. |
| `patient_code` | `str \| None` | Hospital/patient code. |
| `patient_sex` | `str \| None` | Sex subfield. |
| `patient_birthdate` | `datetime.date \| None` | Patient birthdate. |
| `patient_name` | `str \| None` | Patient name. |
| `recording_startdate` | `datetime.date \| None` | Recording start date from EDF+ subfield. |
| `recording_admin_code` | `str \| None` | Investigation/admin code. |
| `recording_technician` | `str \| None` | Technician/investigator code. |
| `recording_equipment` | `str \| None` | Equipment code. |

### `Signal`

Represents a single channel with header metadata and sample data.

| Field | Type | Description |
|-------|------|-------------|
| `label` | `str` | Signal label (e.g., `"EEG Fp1"`). |
| `transducer_type` | `str` | Transducer type string. |
| `physical_dimension` | `str` | Physical unit (e.g., `"uV"`). |
| `physical_min` | `float` | Minimum physical calibration value. |
| `physical_max` | `float` | Maximum physical calibration value. |
| `digital_min` | `int` | Minimum raw digital value. |
| `digital_max` | `int` | Maximum raw digital value. |
| `prefiltering` | `str` | Pre-filtering description. |
| `samples_per_record` | `int` | Samples per data record for this channel. |
| `sample_rate` | `float` | Sample rate in Hz. |
| `is_annotation` | `bool` | `True` if this is an EDF Annotations channel. |
| `index` | `int` | 0-based position in the file's signal list. |

#### Accessing samples

```python
signal.samples            # Full sample array (loads lazily on first access)
signal.load(start, stop)  # Load a slice by index, seconds, datetime, or timedelta
```

The `load()` and `load_with_timestamps()` methods accept flexible position arguments:

- `int` -- sample index
- `float` -- seconds from recording start
- `datetime.datetime` -- absolute time
- `datetime.timedelta` -- offset from recording start

You can also use `onset`/`duration` as alternatives to `start`/`stop`:

```python
# These are equivalent:
signal.load(start=10.0, stop=15.0)
signal.load(onset=10.0, duration=5.0)
```

### `Annotation`

A frozen dataclass representing a single EDF+ annotation from a TAL block.

| Field | Type | Description |
|-------|------|-------------|
| `onset` | `float` | Onset time in seconds from recording start. |
| `duration` | `float \| None` | Event duration in seconds, or `None` if unspecified. |
| `text` | `str` | The annotation text. |

## Examples

### Read raw digital samples

```python
with read_edf("recording.edf", physical=False) as edf:
    raw = edf[0].samples  # numpy int16 array
```

### Use float32 for lower memory

```python
import numpy as np
from edfplus import read_edf

with read_edf("recording.edf", dtype=np.float32) as edf:
    samples = edf[0].samples  # float32 instead of float64
```

### Timezone-aware datetimes

```python
from datetime import timezone, timedelta
from edfplus import read_edf

tz = timezone(timedelta(hours=1))  # CET

with read_edf("recording.edf", tzinfo=tz) as edf:
    print(edf.header.start_datetime)  # timezone-aware
```

### Get samples with absolute timestamps

```python
with read_edf("recording.edf") as edf:
    signal = edf["EEG Fp1"]
    samples, timestamps = signal.load_with_timestamps(
        onset=0.0, duration=10.0, time_format="datetime"
    )
    # timestamps is a datetime64[us] array
```
