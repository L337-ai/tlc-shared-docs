"""Tests for config loading and project root detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tlc_shared_docs.config import (
    GITIGNORE_CONTENT,
    SharedFile,
    SourceRepo,
    ensure_shared_dir,
    find_project_root,
    load_config,
    resolve_local_path,
    shared_dir_path,
)


class TestFindProjectRoot:
    def test_finds_git_root(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        assert find_project_root(sub) == tmp_path

    def test_finds_pyproject_root(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("")
        assert find_project_root(tmp_path) == tmp_path

    def test_raises_when_no_root(self, tmp_path: Path):
        # tmp_path itself has no markers; create a deep subdir with none
        deep = tmp_path / "x" / "y" / "z"
        deep.mkdir(parents=True)
        with pytest.raises(FileNotFoundError, match="project root"):
            find_project_root(deep)


class TestEnsureSharedDir:
    def test_creates_dir_and_gitignore(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        sdir = ensure_shared_dir(tmp_path)
        assert sdir.is_dir()
        gitignore = sdir / ".gitignore"
        assert gitignore.exists()
        assert gitignore.read_text(encoding="utf-8") == GITIGNORE_CONTENT

    def test_idempotent(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        ensure_shared_dir(tmp_path)
        # Call again — should not fail or overwrite
        ensure_shared_dir(tmp_path)


class TestResolveLocalPath:
    def test_relative_path(self, tmp_path: Path):
        result = resolve_local_path(tmp_path, "foo.md")
        assert result == shared_dir_path(tmp_path) / "foo.md"

    def test_absolute_path(self, tmp_path: Path):
        result = resolve_local_path(tmp_path, "/docs/other/bar.md")
        assert result == tmp_path / "docs" / "other" / "bar.md"


class TestLoadConfig:
    def test_loads_valid_config(self, configured_project):
        root, _ = configured_project
        conf = load_config(root)
        assert isinstance(conf.source_repo, SourceRepo)
        assert conf.source_repo.url == "https://github.com/github/gitignore.git"
        assert conf.source_repo.branch == "main"
        assert len(conf.shared_files) == 1
        assert conf.shared_files[0].action == "get"

    def test_defaults_action_to_get(self, fake_project):
        root, shared_dir = fake_project
        config = {
            "source_repo": {"url": "https://example.com/repo.git"},
            "shared_files": [
                {"remote_path": "a.md", "local_path": "a.md"}
            ],
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")
        conf = load_config(root)
        assert conf.shared_files[0].action == "get"
        assert conf.source_repo.branch == "main"

    def test_raises_when_missing(self, fake_project):
        root, _ = fake_project
        with pytest.raises(FileNotFoundError):
            load_config(root)
