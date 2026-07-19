# EDFplus

[![tests](https://github.com/michaelwayman/edfplus/actions/workflows/tests.yml/badge.svg)](https://github.com/michaelwayman/edfplus/actions/workflows/tests.yml)
[![codecov](https://codecov.io/gh/michaelwayman/edfplus/graph/badge.svg?token=90NMY2UHHO)](https://codecov.io/gh/michaelwayman/edfplus)
[![PyPI](https://img.shields.io/pypi/v/edfplus)](https://pypi.org/project/edfplus/)

EDFplus is a python package for working with [European Data Format](https://www.edfplus.info/) files (EDF, EDF+C, EDF+D)
files.

# Development

```zsh
# Run tests
uv run pytest tests/

# Lint & format
uv run ruff check --fix
uv run ruff format

# Static type check
uv run ty check
```