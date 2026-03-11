"""Shared fixtures for tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Public repo used for integration tests
PUBLIC_REPO_URL = "https://github.com/github/gitignore.git"
PUBLIC_REPO_BRANCH = "main"
# A file known to exist in github/gitignore
PUBLIC_REPO_FILE = "Python.gitignore"


@pytest.fixture()
def fake_project(tmp_path: Path):
    """Create a minimal fake project with a .git marker and shared.json."""
    # Create .git marker so find_project_root works
    (tmp_path / ".git").mkdir()

    shared_dir = tmp_path / "docs" / "source" / "shared"
    shared_dir.mkdir(parents=True)

    return tmp_path, shared_dir


@pytest.fixture()
def sample_config() -> dict:
    """Return a sample shared.json dict pointing at the public repo."""
    return {
        "source_repo": {
            "url": PUBLIC_REPO_URL,
            "branch": PUBLIC_REPO_BRANCH,
        },
        "shared_files": [
            {
                "remote_path": PUBLIC_REPO_FILE,
                "local_path": "python_gitignore.txt",
                "action": "get",
            },
        ],
    }


@pytest.fixture()
def configured_project(fake_project, sample_config):
    """A fake project with shared.json already written."""
    root, shared_dir = fake_project
    config_file = shared_dir / "shared.json"
    config_file.write_text(json.dumps(sample_config), encoding="utf-8")
    return root, shared_dir
