# CLAUDE.md — tlc-doc-share

This file provides guidance to Claude Code when working in this repository.

---

## What This Is

`tlc-doc-share` is a lightweight Python CLI utility that synchronizes documentation files between Git repositories. It supports pull (`get`) and push operations controlled by a single `shared.json` config file. No framework dependencies — just GitPython and standard Python.

---

## Windows Bash Workaround

On Windows, the Bash tool sometimes fails to capture stdout and may report a false exit code. Prefer dedicated tools (Read, Write, Edit, Glob, Grep) over Bash equivalents whenever possible.

If a Bash command returns no output or a suspicious exit code, retry with `2>&1 | tee /dev/stderr` appended to route output through stderr, which is captured reliably.

Always check actual output text to determine success or failure — do not rely solely on the exit code.

---

## Setup and Installation

```bash
# Install dependencies
poetry install

# Verify CLI is available
poetry run tlc-shared-docs --version
```

---

## Running Tests

```bash
# Always use poetry run — not pytest directly
poetry run pytest

# Verbose output
poetry run pytest -v

# Specific test file
poetry run pytest tests/test_config.py -v

# Skip integration tests (default — they require real Git access)
poetry run pytest -m "not integration"

# Run integration tests only (requires network + git credentials)
poetry run pytest -m integration -v
```

---

## Linting and Type Checking

```bash
poetry run flake8 tlc_shared_docs/ tests/
poetry run mypy tlc_shared_docs/
```

---

## Project Structure

```
tlc_shared_docs/
├── __init__.py     # Version string
├── cli.py          # CLI entry point (argparse)
├── config.py       # Config loading, path resolution, glob utilities
├── core.py         # get_files() / push_files() orchestration
└── git_ops.py      # GitPython wrapper (sparse checkout, push)

tests/
├── conftest.py     # Fixtures: fake_project, configured_project, sample_config
├── test_config.py  # Config loading, path resolution, glob patterns
├── test_core.py    # get/push operations, central mode, dry-run
└── test_git_ops.py # Sparse checkout, file listing, git operations
```

---

## Key Behaviors to Know

- **Config location:** `docs/source/shared/shared.json` in the consuming repo
- **Relative `local_path`** resolves under `docs/source/shared/`
- **Absolute `local_path`** (starts with `/`) resolves from project root
- **Glob patterns** supported for `get` only — not for `push`
- **Auto-gitignore:** fetched files are not committed; only `shared.json` is tracked
- **Project root detection:** walks up from cwd looking for `.git`, `pyproject.toml`, or `setup.py`
- **Sparse checkout:** only the requested files are fetched (`depth=1`)

---

## Code Style

- Absolute imports only: `from tlc_shared_docs.config import find_project_root`
- Full type hints on all public functions
- Comment every 3–7 lines when logic is non-obvious
- No hardcoded paths — resolve via `find_project_root()` and config
