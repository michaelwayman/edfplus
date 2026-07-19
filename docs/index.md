# edfplus

A Python library for reading and working with EDF (European Data Format) and EDF+ files — a standard format for storing biosignal recordings such as EEG, PSG, and other physiological time-series data.

## Installation

```bash
pip install edfplus
```

## Quick Start

```python
from edfplus import read_edf

with read_edf("recording.edf") as edf:
    print(edf.header.start_datetime)
    print(edf.signals[0].label)
    print(edf.signals[0].samples)
```

## Features
Parse EDF/EDF+ binary file headers (global + per-signal)
Read and scale data records from digital int16 samples to physical values
Handle EDF+ extensions: continuous (EDF+C) and discontinuous (EDF+D) files
Parse Time-stamped Annotations Lists (TAL)
Lazy signal loading for memory efficiency
Fully typed Python API

## Why edfplus?

Existing Python EDF libraries fall short for modern biosignal workflows: incomplete EDF+D support corrupts long clinical recordings, naive datetime handling breaks ML timestamp alignment, and eager full-file loading causes OOM failures at scale. `edfplus` was purpose-built to solve these problems with correct discontinuous recording support, explicit timezone control, and memory-efficient streaming reads.

Read the full [Motivation](motivation.md) page for a detailed technical discussion.
