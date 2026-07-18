# Project Structure

```
edfplus/
├── src/
│   └── edfplus/          # Main library package
│       ├── __init__.py   # Public API surface
│       └── py.typed      # PEP 561 marker — this is a typed package
├── tests/                # pytest test suite
├── edf.md                # Full EDF/EDF+ format specification reference
├── pyproject.toml        # Project metadata, dependencies, tool config
├── uv.lock               # Locked dependency versions
└── .python-version       # Pinned Python version for uv
```

## Conventions
- All library code lives under `src/edfplus/`. Use the `src` layout — do not put importable code at the repo root.
- Public API is exported through `src/edfplus/__init__.py`.
- Tests live in `tests/` and mirror the module structure they cover.
- `edf.md` is the authoritative spec reference — consult it when implementing any parsing logic.

## Adding new modules
Place new modules inside `src/edfplus/` and re-export anything that should be part of the public API from `__init__.py`.
