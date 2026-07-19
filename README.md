# EDFplus

[![tests](https://github.com/michaelwayman/edfplus/actions/workflows/tests.yml/badge.svg)](https://github.com/michaelwayman/edfplus/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/michaelwayman/edfplus/graph/badge.svg?token=90NMY2UHHO)](https://codecov.io/gh/michaelwayman/edfplus)
[![PyPI](https://img.shields.io/pypi/v/edfplus)](https://pypi.org/project/edfplus/)

A typed Python library for reading [EDF and EDF+](https://www.edfplus.info/) biosignal files.

## What is EDF?

[European Data Format (EDF)](https://www.edfplus.info/) is a widely adopted, open standard for storing multichannel biological and physical signals such as EEG, EMG, ECG, polysomnography (PSG), and other physiological time-series recordings. An EDF file consists of a fixed-size ASCII header followed by 16-bit integer data records, making it compact and simple to parse.

**EDF+** extends the original format with:

- Continuous (`EDF+C`) and discontinuous (`EDF+D`) recording modes
- Time-stamped Annotations Lists (TALs) embedded directly in the data stream
- Structured patient and recording identification subfields

The full specification is available at [edfplus.info](https://www.edfplus.info/).

## Installation

```bash
pip install edfplus
```

Requires Python 3.14+ and NumPy.

## Quickstart

```python
from edfplus import read_edf

with read_edf("recording.edf") as edf:
    # Inspect the header
    print(edf.header.variant)        # "EDF", "EDF+C", or "EDF+D"
    print(edf.header.start_datetime) # Recording start time
    print(edf.header.num_signals)    # Total signal count

    # Iterate over signals
    for signal in edf.signals:
        print(f"{signal.label}: {signal.sample_rate} Hz, {len(signal.samples)} samples")

    # Access a signal by label or index
    eeg = edf["EEG Fp1"]
    first = edf[0]

    # Load a time slice (seconds)
    chunk = eeg.load(start=10.0, stop=20.0)

    # Get samples with timestamps
    samples, timestamps = eeg.load_with_timestamps(onset=5.0, duration=3.0)

    # Read EDF+ annotations
    for ann in edf.annotations:
        print(f"{ann.onset:.2f}s: {ann.text}")
```

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

EDF+ extended patient subfields (all `None` for plain EDF):

| Field | Type | Description |
|-------|------|-------------|
| `patient_code` | `str \| None` | Hospital/patient code. |
| `patient_sex` | `str \| None` | Sex subfield. |
| `patient_birthdate` | `datetime.date \| None` | Patient birthdate. |
| `patient_name` | `str \| None` | Patient name. |

EDF+ extended recording subfields (all `None` for plain EDF):

| Field | Type | Description |
|-------|------|-------------|
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

## Motivation

Several Python libraries exist for reading EDF files, but none adequately address the requirements of modern biosignal workflows — particularly long-duration clinical recordings, rigorous timestamp alignment for machine learning, and memory constraints at scale.

### Discontinuous recordings (EDF+D)

The EDF+ specification defines two recording modes: continuous (`EDF+C`) and discontinuous (`EDF+D`). Discontinuous mode is essential for polysomnography (PSG) and other long-duration clinical studies — recordings that routinely exceed 10 hours — where pauses occur due to bathroom breaks, patient restlessness, impedance checks, or equipment adjustments. Some existing libraries (e.g., pyedflib) do not support EDF+D at all. Others silently concatenate data records across temporal gaps, producing a continuous array that misrepresents the actual timeline and corrupts any downstream analysis that depends on accurate sample timing.

`edfplus` correctly parses EDF+D time-stamped annotation lists (TALs) to identify discontinuities and exposes them through a straightforward API, preserving the true temporal structure of the recording.

### Timezone-aware timestamps

The EDF+ specification is ambiguous regarding timezones: the startdate field is described as local time at the recording site, but no formal mechanism exists to encode the timezone itself. When patient data is anonymized and recording location is redacted — standard practice for research datasets — the timezone becomes unrecoverable from the file alone.

Existing libraries typically handle this by either assuming UTC or returning naive `datetime` objects, leaving the burden of timezone resolution on the caller. For machine learning and predictive modeling on biosignals, this is insufficient. Ground-truth labels, environmental covariates, and other time-aligned data sources must share a consistent temporal reference. Misaligned timeseries make supervised learning, forecasting, and cross-modal fusion impossible.

`edfplus` accepts an explicit `tzinfo` parameter at read time, attaching timezone information to all parsed datetimes and enabling correct absolute timestamp recovery for every sample in the recording.

### Memory efficiency at scale

High-density PSG recordings generate large files. Consider a typical configuration: 24 signals sampled at 512 Hz for 10 hours. Read into NumPy as the default `float64` dtype, that is:

```
24 × 512 × 36,000 seconds × 8 bytes = ~3.5 GB per signal set
```

With standard float64 arrays, total memory consumption approaches **28 GB** — exceeding the RAM of most workstations and virtually all cloud ML instances.

`edfplus` provides three levers to control memory footprint:

- **Configurable dtype** — pass `dtype=numpy.float32` to halve memory usage while retaining physical scaling.
- **Raw digital access** — set `physical=False` to read the native int16 samples directly, reducing the footprint to approximately **0.9 GB** for the same recording.
- **Lazy and streaming reads** — samples are loaded on demand rather than eagerly materialized. Use `signal.load(start, stop)` to read only the segments your pipeline needs, preventing OOM errors in memory-constrained environments.

## Roadmap

The next release will introduce configurable **interpolation and downsampling** strategies, giving users explicit control over the fidelity-vs-resource trade-off when working with multi-rate signal files. This is a deliberate design contrast with libraries (e.g., `mne`) that automatically upsample lower-rate signals to match the highest rate in the file — synthesizing samples that do not exist in the original recording and inflating memory usage unnecessarily. `edfplus` will instead allow users to choose a resampling strategy (or none at all), preserving data integrity by default and only introducing synthetic samples when explicitly requested.

## Development

```bash
# Run tests
uv run pytest tests/

# Lint & format
uv run ruff check --fix
uv run ruff format

# Static type check
uv run ty check
```

## License

See [LICENSE](LICENSE) for details.
