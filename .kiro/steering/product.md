# Product: edfplus

A Python library for reading and working with EDF (European Data Format) and EDF+ files — a standard format for storing biosignal recordings such as EEG, PSG, and other physiological time-series data.

## Core responsibilities
- Parse EDF/EDF+ binary file headers (global + per-signal)
- Read and scale data records from digital int16 samples to physical values
- Handle EDF+ extensions: continuous (`EDF+C`) and discontinuous (`EDF+D`) files, TAL (Time-stamped Annotations List) parsing, and the logarithmic float encoding (edffloat)
- Expose a clean, typed Python API for downstream signal processing

## Reference spec
Full format details are documented in `edf.md` at the repo root, covering file layout, header fields, scaling, EDF+ additions, logarithmic transform, and standard text conventions.
