"""Tests for config loading and project root detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tlc_shared_docs.config import (
    GITIGNORE_CONTENT,
    SharedFile,
    SourceRepo,
    central_config_path,
    ensure_shared_dir,
    extract_org_repo,
    find_project_root,
    glob_prefix,
    is_glob,
    load_config,
    load_hashes,
    resolve_local_path,
    save_hashes,
    shared_dir_path,
)


class TestFindProjectRoot:
    def test_walks_up_to_git_directory(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        assert find_project_root(sub) == tmp_path

    def test_finds_pyproject_toml_as_root_marker(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text("")
        assert find_project_root(tmp_path) == tmp_path

    def test_raises_when_no_root_marker_exists(self, tmp_path: Path):
        deep = tmp_path / "x" / "y" / "z"
        deep.mkdir(parents=True)
        with pytest.raises(FileNotFoundError, match="project root"):
            find_project_root(deep)


class TestEnsureSharedDir:
    def test_creates_dir_and_gitignore_on_first_call(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        sdir = ensure_shared_dir(tmp_path)
        assert sdir.is_dir()
        gitignore = sdir / ".gitignore"
        assert gitignore.exists()
        assert gitignore.read_text(encoding="utf-8") == GITIGNORE_CONTENT

    def test_second_call_does_not_overwrite_gitignore(self, tmp_path: Path):
        (tmp_path / ".git").mkdir()
        ensure_shared_dir(tmp_path)
        ensure_shared_dir(tmp_path)


class TestResolveLocalPath:
    def test_relative_path_resolves_under_shared_dir(self, tmp_path: Path):
        result = resolve_local_path(tmp_path, "foo.md")
        assert result == shared_dir_path(tmp_path) / "foo.md"

    def test_absolute_path_resolves_from_project_root(self, tmp_path: Path):
        result = resolve_local_path(tmp_path, "/docs/other/bar.md")
        assert result == tmp_path / "docs" / "other" / "bar.md"


class TestLoadConfig:
    def test_parses_valid_config_with_all_fields(self, configured_project):
        root, _ = configured_project
        conf = load_config(root)
        assert isinstance(conf.source_repo, SourceRepo)
        assert conf.source_repo.url == "https://github.com/github/gitignore.git"
        assert conf.source_repo.branch == "main"
        assert len(conf.shared_files) == 1
        assert conf.shared_files[0].action == "get"

    def test_defaults_action_to_get_and_branch_to_main(self, fake_project):
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

    def test_raises_when_config_file_missing(self, fake_project):
        root, _ = fake_project
        with pytest.raises(FileNotFoundError):
            load_config(root)


class TestIsGlob:
    def test_plain_path_is_not_glob(self):
        assert is_glob("docs/guide.md") is False

    def test_single_star_detected(self):
        assert is_glob("*.md") is True

    def test_double_star_detected(self):
        assert is_glob("stories/**/*") is True

    def test_question_mark_detected(self):
        assert is_glob("file?.txt") is True

    def test_bracket_detected(self):
        assert is_glob("file[0-9].txt") is True


class TestGlobPrefix:
    def test_no_prefix_when_pattern_starts_with_glob(self):
        assert glob_prefix("*.md") == ""

    def test_single_dir_prefix(self):
        assert glob_prefix("stories/**/*") == "stories"

    def test_nested_dir_prefix(self):
        assert glob_prefix("docs/source/**/*.md") == "docs/source"

    def test_full_path_returned_when_no_glob_chars(self):
        assert glob_prefix("docs/source/file.md") == "docs/source/file.md"


class TestExtractOrgRepo:
    def test_https_with_git_suffix(self):
        assert extract_org_repo("https://github.com/L337-ai/tlc-shared-docs.git") == "L337-ai/tlc-shared-docs"

    def test_https_without_git_suffix(self):
        assert extract_org_repo("https://github.com/L337-ai/tlc-shared-docs") == "L337-ai/tlc-shared-docs"

    def test_https_trailing_slash_stripped(self):
        assert extract_org_repo("https://github.com/L337-ai/tlc-shared-docs/") == "L337-ai/tlc-shared-docs"

    def test_ssh_shorthand_format(self):
        assert extract_org_repo("git@github.com:L337-ai/tlc-shared-docs.git") == "L337-ai/tlc-shared-docs"

    def test_ssh_shorthand_without_git_suffix(self):
        assert extract_org_repo("git@github.com:org/repo") == "org/repo"

    def test_full_ssh_url_format(self):
        assert extract_org_repo("ssh://git@github.com/org/repo.git") == "org/repo"

    def test_dots_and_underscores_in_names(self):
        assert extract_org_repo("https://github.com/my.org/my_repo.git") == "my.org/my_repo"

    def test_invalid_url_raises_valueerror(self):
        with pytest.raises(ValueError, match="Cannot extract"):
            extract_org_repo("not-a-url")


class TestCentralConfigPath:
    def test_maps_org_repo_to_configs_dir(self):
        assert central_config_path("L337-ai/my-app") == ".configs/L337-ai/my-app.json"

    def test_simple_org_repo(self):
        assert central_config_path("org/repo") == ".configs/org/repo.json"


class TestLoadConfigCentralMode:
    def test_central_mode_parsed_from_json(self, fake_project):
        root, shared_dir = fake_project
        config = {
            "mode": "central",
            "source_repo": {"url": "https://example.com/shared-docs.git", "branch": "main"},
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")
        conf = load_config(root)
        assert conf.mode == "central"
        assert conf.shared_files == []

    def test_defaults_mode_to_local_when_not_specified(self, configured_project):
        root, _ = configured_project
        conf = load_config(root)
        assert conf.mode == "local"


class TestHashes:
    def test_returns_empty_dict_when_no_file(self, fake_project):
        root, _ = fake_project
        assert load_hashes(root) == {}

    def test_roundtrip_save_and_load(self, fake_project):
        root, _ = fake_project
        hashes = {"file.md": "abc123", "other.md": "def456"}
        save_hashes(root, hashes)
        assert load_hashes(root) == hashes

    def test_overwrite_replaces_previous_hashes(self, fake_project):
        root, _ = fake_project
        save_hashes(root, {"a.md": "sha1"})
        save_hashes(root, {"a.md": "sha2", "b.md": "sha3"})
        loaded = load_hashes(root)
        assert loaded == {"a.md": "sha2", "b.md": "sha3"}

    def test_corrupt_json_returns_empty_dict(self, fake_project):
        root, shared_dir = fake_project
        (shared_dir / ".shared-hashes.json").write_text("not valid json")
        assert load_hashes(root) == {}
