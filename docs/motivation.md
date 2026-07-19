# Motivation

Several Python libraries exist for reading EDF files, but none adequately address the requirements of modern biosignal workflows — particularly long-duration clinical recordings, rigorous timestamp alignment for machine learning, and memory constraints at scale. `edfplus` was built to fill these gaps.

## Discontinuous recordings (EDF+D)

The EDF+ specification defines two recording modes: continuous (`EDF+C`) and discontinuous (`EDF+D`). Discontinuous mode is essential for polysomnography (PSG) and other long-duration clinical studies — recordings that routinely exceed 10 hours — where pauses occur due to bathroom breaks, patient restlessness, impedance checks, or equipment adjustments.

Some existing libraries (e.g., pyedflib) do not support EDF+D at all. Others silently concatenate data records across temporal gaps, producing a continuous array that misrepresents the actual timeline and corrupts any downstream analysis that depends on accurate sample timing.

`edfplus` correctly parses EDF+D time-stamped annotation lists (TALs) to identify discontinuities and exposes them through a straightforward API, preserving the true temporal structure of the recording.

!!! example "Reading a discontinuous file"

    ```python
    from edfplus import read_edf

    with read_edf("sleep_study.edf") as edf:
        print(edf.header.variant)  # "EDF+D"

        # Timestamps correctly reflect gaps in the recording
        signal = edf["EEG Fp1"]
        samples, timestamps = signal.load_with_timestamps(onset=0.0, duration=60.0)
    ```

## Timezone-aware timestamps

The EDF+ specification is ambiguous regarding timezones: the startdate field is described as local time at the recording site, but no formal mechanism exists to encode the timezone itself. When patient data is anonymized and recording location is redacted — standard practice for research datasets — the timezone becomes unrecoverable from the file alone.

Existing libraries typically handle this by either assuming UTC or returning naive `datetime` objects, leaving the burden of timezone resolution entirely on the caller. For machine learning and predictive modeling on biosignals, this is insufficient. Ground-truth labels, environmental covariates, and other time-aligned data sources must share a consistent temporal reference. Misaligned timeseries make supervised learning, forecasting, and cross-modal fusion impossible.

`edfplus` accepts an explicit `tzinfo` parameter at read time, attaching timezone information to all parsed datetimes and enabling correct absolute timestamp recovery for every sample in the recording.

!!! example "Attaching timezone information"

    ```python
    from datetime import timezone, timedelta
    from edfplus import read_edf

    # Recording was made in US Eastern Time
    eastern = timezone(timedelta(hours=-5))

    with read_edf("recording.edf", tzinfo=eastern) as edf:
        # All datetimes are now timezone-aware
        print(edf.header.start_datetime)
        # datetime.datetime(2024, 3, 15, 22, 30, 0, tzinfo=...)

        signal = edf["EEG Fp1"]
        _, timestamps = signal.load_with_timestamps(
            onset=0.0, duration=10.0, time_format="datetime"
        )
        # timestamps are absolute, timezone-aware datetime64 values
    ```

This approach makes it straightforward to align EDF signal data with external event logs, actigraphy, environmental sensors, or any other timestamped data source — a prerequisite for multi-modal ML pipelines.

## Memory efficiency at scale

High-density PSG recordings generate large files. Consider a typical clinical configuration: 24 signals sampled at 512 Hz for 10 hours. Read into NumPy as the default `float64` dtype, that is:

```
24 signals × 512 samples/sec × 36,000 seconds × 8 bytes = ~3.5 GB per signal set
```

With standard float64 arrays, total memory consumption approaches **28 GB** — exceeding the RAM of most workstations and virtually all cloud ML training instances.

`edfplus` provides three levers to control memory footprint:

### Configurable dtype

Pass a smaller floating-point type to halve (or further reduce) memory usage while retaining physical unit scaling:

```python
import numpy as np
from edfplus import read_edf

with read_edf("large_study.edf", dtype=np.float32) as edf:
    # Samples are scaled to physical units but stored as float32
    # Memory usage: ~14 GB instead of ~28 GB
    samples = edf["EEG Fp1"].samples
```

### Raw digital access

Bypass physical scaling entirely and work with the native int16 samples stored in the file:

```python
from edfplus import read_edf

with read_edf("large_study.edf", physical=False) as edf:
    # Raw int16 values — 2 bytes per sample
    # Memory usage: ~0.9 GB for 24 channels × 512 Hz × 10 hours
    raw = edf["EEG Fp1"].samples
```

This is particularly useful for preprocessing pipelines that apply their own normalization, or for feeding data into models that expect integer inputs.

### Lazy and streaming reads

By default, `edfplus` does not load samples into memory until they are accessed. Combined with slice-based loading, this enables streaming workflows that process recordings in chunks without ever materializing the full dataset:

```python
from edfplus import read_edf

with read_edf("large_study.edf", dtype=np.float32) as edf:
    signal = edf["EEG Fp1"]

    # Process in 30-second epochs — only one epoch in memory at a time
    for epoch_start in range(0, 36000, 30):
        chunk = signal.load(start=float(epoch_start), stop=float(epoch_start + 30))
        # Process chunk...
```

This prevents OOM errors in memory-constrained environments such as containerized ML pipelines, CI runners, and edge devices.

## Roadmap

The next release will introduce configurable **interpolation and downsampling** strategies, giving users explicit control over the fidelity-vs-resource trade-off when working with multi-rate signal files.

This is a deliberate design contrast with libraries (e.g., `mne`) that automatically upsample lower-rate signals to match the highest rate in the file — synthesizing samples that do not exist in the original recording and inflating memory usage unnecessarily.

`edfplus` will instead allow users to choose a resampling strategy (or none at all), preserving data integrity by default and only introducing synthetic samples when explicitly requested.
