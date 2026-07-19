# edfplus

A Python library for reading and working with EDF (European Data Format) and EDF+ files — a standard format for storing biosignal recordings such as EEG, PSG, and other physiological time-series data.

## What is EDF+?

[European Data Format (EDF+)](https://www.edfplus.info/) is a widely adopted, open standard for storing multichannel biological and physical signals such as EEG, EMG, ECG, polysomnography (PSG), and other physiological time-series recordings. An EDF file consists of a fixed-size ASCII header followed by 16-bit integer data records, making it compact and simple to parse.

## Features

| Category              | Feature                                                |     |
| --------------------- | ------------------------------------------------------ | --- |
| 📄 **Format Support** | EDF / EDF+                                             | ✅  |
|                       | EDF+C / EDF+D                                          | ✅  |
| 📂 **Read From**      | String path or `PathLike`                              | ✅  |
|                       | Binary file objects                                    | ✅  |
|                       | Any seekable stream (`BinaryIO`)                       | ✅  |
| 🏷️ **Metadata**       | Full header field access (patient, recording, signals) | ✅  |
|                       | EDF+ annotations & TALs                                | ✅  |
|                       | Normalized & typed subfields                           | ✅  |
| 📊 **Signal Data**    | Lazy loading                                           | ✅  |
|                       | Cherry-pick data                                       | ✅  |
|                       | Or grab everything at once                             | ✅  |
|                       | Physical (scaled float) or digital (raw int16)         | ✅  |
|                       | Pick your dtype — your RAM will thank you              | ✅  |
| 🕐 **Timestamps**     | Timezone correction                                    | ✅  |
|                       | Per-sample timestamps (seconds)                        | ✅  |
|                       | Per-sample datetimes (absolute)                        | ✅  |
|                       | Onset-relative timing                                  | ✅  |
| 🔎 **Read Filters**   | Slice by seconds or by index                           | ✅  |
|                       | Slice by datetimes or durations                        | ✅  |
| 🧠 **Fully Typed**    | Complete type annotations across the public API        | ✅  |
|                       | PEP 561 `py.typed` — your type checker is happy        | ✅  |

## Installation

Requires Python 3.12+ and NumPy.

```bash
# uv
uv add edfplus

# others
poetry add edfplus
pip install edfplus
```

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


## Why edfplus?

Existing Python EDF libraries fall short for modern biosignal workflows: incomplete EDF+D support corrupts long clinical recordings, naive datetime handling breaks ML timestamp alignment, and eager full-file loading causes OOM failures at scale. `edfplus` was purpose-built to solve these problems with correct discontinuous recording support, explicit timezone control, and memory-efficient streaming reads.

Read the full [Motivation](motivation.md) page for a detailed technical discussion.


## Roadmap

The next release will introduce configurable **interpolation and downsampling** strategies, giving users explicit control over the fidelity-vs-resource trade-off when working with multi-rate signal files. This includes streaming interpolation that operates on chunks rather than requiring the full signal in memory.

This is a deliberate design contrast with libraries (e.g., `mne`) that automatically upsample lower-rate signals to match the highest rate in the file — synthesizing samples that do not exist in the original recording and inflating memory usage unnecessarily.

`edfplus` will instead allow users to choose a resampling strategy (or none at all), preserving data integrity by default and only introducing synthetic samples when explicitly requested.
