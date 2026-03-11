# Coding Agent Protocol — tlc-doc-share

You are an autonomous coding agent working in `tlc-doc-share`, a standalone Python CLI utility for synchronizing documentation files between Git repositories.

---

## Required Preparation

Read these before every task:

- `README.md` — usage, config format, CLI commands
- `tests/TESTABILITY.md` — test structure and coverage expectations (if present)

Run all tests via Poetry:

```bash
poetry run pytest
```

Never use bare `pytest` or `python -m pytest`.

---

## Coding Rules

### Always ask before guessing
When a task is ambiguous, stop and ask. Do not infer intent from partial context.

### Absolute imports only
```python
from tlc_shared_docs.config import find_project_root   # correct
from .config import find_project_root                  # wrong
```

### Match existing signatures exactly
Before adding or modifying a function, read its current signature and all call sites. Do not change signatures without updating all callers.

### No silent failures
Every `except` block that suppresses an exception must log at WARNING or ERROR level. Never use bare `except: pass` or catch-and-return-None without a log statement.

```python
# Wrong
try:
    content = path.read_text()
except Exception:
    return None

# Correct
try:
    content = path.read_text()
except Exception:
    logger.warning("Failed to read %s", path, exc_info=True)
    return None
```

### Explicit type hints
All public functions must be fully type-hinted. Never use bare `Any` or `object` when a concrete type is available.

### No hardcoded paths
All file path logic must go through `find_project_root()` and the config resolution functions in `config.py`. No hardcoded directory names.

### Composition over inheritance
Prefer passing collaborators as arguments over subclassing. Only subclass when polymorphic behavior is genuinely required.

### Validate at entry points
Check config fields, path existence, and git credentials at the start of `get_files()` and `push_files()` — not buried inside helpers. Fail fast with a clear message.

### Backward compatibility
If you change a public function signature or config field name, document the breaking change. Do not silently change behavior.

---

## Testing Rules

### Always use explicit test doubles — no mocking frameworks

```python
# Wrong — hides contract changes
from unittest.mock import MagicMock
repo = MagicMock()
repo.git.fetch.return_value = None

# Correct — explicit stub that implements the contract
class _StubRepo:
    def __init__(self):
        self.fetched = []
    def fetch(self, remote, branch, **kwargs):
        self.fetched.append((remote, branch))
```

Forbidden test utilities:
- `unittest.mock.MagicMock` or `Mock`
- `pytest.monkeypatch`
- `@patch` decorators

Preferred:
- Explicit stub/fake classes
- `tmp_path` fixture for real filesystem operations
- `conftest.py` fixtures (`fake_project`, `configured_project`) for repo-shaped temp directories

### Test isolation
Every test must clean up after itself. No shared state between tests. No temp directories that survive test teardown.

### Each test must explain what breaks if it fails
Test names should describe the behavior, not the implementation:
```python
def test_relative_local_path_resolves_under_shared_dir():  # correct
def test_resolve_local_path():                              # too vague
```

### Integration tests require real Git access
Mark with `@pytest.mark.integration`. Do not run by default. The existing integration tests use the public `github/gitignore` repo — do not change the target without updating all integration tests.

---

## Commenting Preferences

- Comment every 3–7 lines, or whenever a block has non-obvious logic
- Focus on *why/how*, not *what*
- If it takes 2+ reads to understand, add a comment
- Use only ASCII characters — no Unicode arrows, checkmarks, or emoji

```python
# Sparse checkout limits the clone to only the requested paths.
# Depth=1 avoids fetching full history — we only need the latest content.
```

---

## Workflow

- **TDD:** Write or update the test before the implementation when adding new behavior
- **Minimal PR surface:** Only touch files required by the task. Do not refactor unrelated code
- **One concern per change:** If you find a second issue while working, note it and finish the first task
- **Imperative commit messages:** "Add glob support for push operations" not "Updated push"

---

## Developer Reference

```bash
# Install
poetry install

# Test (skip integration)
poetry run pytest -m "not integration" -v

# Test (all, requires git credentials)
poetry run pytest -v

# Lint
poetry run flake8 tlc_shared_docs/ tests/

# Type check
poetry run mypy tlc_shared_docs/

# Run CLI
poetry run tlc-shared-docs get --dry-run
poetry run tlc-shared-docs push --dry-run
```

---

## Bug Policy

If you find a bug or missing feature in a dependency (GitPython, etc.):

1. **Stop.** Do not implement a workaround.
2. Add a `# TODO: blocked by <library> issue — <brief description>` comment where affected.
3. Skip the affected test with `@pytest.mark.skip(reason="...")`.
4. Report the issue to the user with a clear description of what's missing and why a workaround is inappropriate.
