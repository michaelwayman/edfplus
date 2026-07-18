# Tech Stack

## Language & Runtime
- Python ≥ 3.14 (use modern syntax: `match`, `type` aliases, etc.)

## Build System
- **uv** — package manager and build backend (`uv_build`)
- All commands are run via `uv run`

## Dependencies
- `numpy >=2.5.1` — primary dependency for array operations and int16 sample handling

## Dev Dependencies
- `pytest` — test runner
- `ruff` — linter and formatter
- `ty` — static type checker (astral's new type checker, not mypy)

## Code Style (ruff config)
- Line length: **120**
- Indent width: **4 spaces**
- Target: `py314`
- Import sorting (`I`) is enabled — imports must be sorted
- Google style docstrings should be used

## Common Commands

```zsh
# Run tests
uv run pytest tests/

# Lint and auto-fix
uv run ruff check --fix

# Format code
uv run ruff format

# Static type check
uv run ty check
```

## Type Checking
Use `ty` (not mypy or pyright). The `ty` source paths include both `src` and `tests`. All public APIs should be fully typed. The `py.typed` marker is present — this is a typed package.
