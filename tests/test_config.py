"""Tests for config loading and project root detection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tlc_shared_docs.config import (
    GITIGNORE_CONTENT,
    SharedFile,
    SourceRepo,
    UploadConfig,
    central_config_path,
    ensure_shared_dir,
    extract_org_repo,
    find_project_root,
    glob_prefix,
    is_glob,
    list_projects,
    load_config,
    load_hashes,
    parse_upload_config,
    resolve_local_path,
    save_hashes,
    shared_dir_path,
    validate_project_name,
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


class TestParseUploadConfig:
    def test_returns_none_when_section_absent(self):
        assert parse_upload_config({}) is None

    def test_returns_none_for_empty_uploads(self):
        assert parse_upload_config({"uploads": {}}) is None

    def test_parses_allowed_and_paths(self):
        data = {"uploads": {"allowed": True, "paths": ["docs/**/*.md", "guides/*.rst"]}}
        result = parse_upload_config(data)
        assert isinstance(result, UploadConfig)
        assert result.allowed is True
        assert result.paths == ["docs/**/*.md", "guides/*.rst"]

    def test_defaults_allowed_to_false(self):
        data = {"uploads": {"paths": ["*.md"]}}
        result = parse_upload_config(data)
        assert result.allowed is False

    def test_defaults_paths_to_empty(self):
        data = {"uploads": {"allowed": True}}
        result = parse_upload_config(data)
        assert result.paths == []


class TestLoadConfigWithUploads:
    def test_uploads_parsed_from_shared_json(self, fake_project):
        root, shared_dir = fake_project
        config = {
            "source_repo": {"url": "https://example.com/repo.git"},
            "shared_files": [],
            "uploads": {"allowed": True, "paths": ["contributions/**/*.md"]},
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")
        conf = load_config(root)
        assert conf.uploads is not None
        assert conf.uploads.allowed is True
        assert conf.uploads.paths == ["contributions/**/*.md"]

    def test_uploads_none_when_absent(self, configured_project):
        root, _ = configured_project
        conf = load_config(root)
        assert conf.uploads is None


class TestMultiProjectConfig:
    """Tests for multi-project shared.json format."""

    def _multi_config(self, default=None):
        """Build a multi-project config dict."""
        config: dict = {
            "projects": {
                "auth": {
                    "source_repo": {"url": "https://github.com/L337-ai/tlc-auth-arch.git"},
                    "mode": "central",
                },
                "events": {
                    "source_repo": {"url": "https://github.com/L337-ai/tlc-events-arch.git", "branch": "dev"},
                    "mode": "central",
                    "shared_files": [
                        {"remote_path": "events/guide.md", "local_path": "events/guide.md", "action": "get"}
                    ],
                },
                "agent-coder": {
                    "source_repo": {"url": "https://github.com/L337-ai/agent-coder.git"},
                    "mode": "central",
                    "uploads": {"allowed": True, "paths": ["agent-coder/**/*.md"]},
                },
            },
        }
        if default:
            config["default_project"] = default
        return config

    def test_selects_named_project(self, fake_project):
        root, shared_dir = fake_project
        (shared_dir / "shared.json").write_text(json.dumps(self._multi_config()), encoding="utf-8")

        conf = load_config(root, project="events")
        assert conf.source_repo.url == "https://github.com/L337-ai/tlc-events-arch.git"
        assert conf.source_repo.branch == "dev"
        assert conf.mode == "central"
        assert len(conf.shared_files) == 1

    def test_uses_default_project_when_none_specified(self, fake_project):
        root, shared_dir = fake_project
        (shared_dir / "shared.json").write_text(
            json.dumps(self._multi_config(default="agent-coder")), encoding="utf-8"
        )

        conf = load_config(root)
        assert conf.source_repo.url == "https://github.com/L337-ai/agent-coder.git"
        assert conf.uploads is not None
        assert conf.uploads.allowed is True

    def test_raises_when_no_project_and_no_default(self, fake_project):
        root, shared_dir = fake_project
        (shared_dir / "shared.json").write_text(json.dumps(self._multi_config()), encoding="utf-8")

        with pytest.raises(ValueError, match="No --project specified"):
            load_config(root)

    def test_raises_when_project_not_found(self, fake_project):
        root, shared_dir = fake_project
        (shared_dir / "shared.json").write_text(json.dumps(self._multi_config()), encoding="utf-8")

        with pytest.raises(ValueError, match="not found"):
            load_config(root, project="nonexistent")

    def test_error_lists_available_projects(self, fake_project):
        root, shared_dir = fake_project
        (shared_dir / "shared.json").write_text(json.dumps(self._multi_config()), encoding="utf-8")

        with pytest.raises(ValueError, match="agent-coder.*auth.*events"):
            load_config(root, project="nope")

    def test_legacy_format_still_works(self, configured_project):
        root, _ = configured_project
        conf = load_config(root)
        assert conf.source_repo.url == "https://github.com/github/gitignore.git"

    def test_project_defaults_branch_to_main(self, fake_project):
        root, shared_dir = fake_project
        (shared_dir / "shared.json").write_text(json.dumps(self._multi_config()), encoding="utf-8")

        conf = load_config(root, project="auth")
        assert conf.source_repo.branch == "main"

    def test_auto_prefixes_local_paths_with_project_name(self, fake_project):
        root, shared_dir = fake_project
        config = {
            "projects": {
                "myproj": {
                    "source_repo": {"url": "https://example.com/repo.git"},
                    "shared_files": [
                        {"remote_path": "guide.md", "local_path": "guide.md", "action": "get"}
                    ],
                },
            },
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")

        conf = load_config(root, project="myproj")
        assert conf.shared_files[0].local_path == "myproj/guide.md"

    def test_skips_prefix_when_local_path_already_starts_with_project_name(self, fake_project):
        root, shared_dir = fake_project
        (shared_dir / "shared.json").write_text(json.dumps(self._multi_config()), encoding="utf-8")

        conf = load_config(root, project="events")
        # Original local_path was "events/guide.md" — already starts with "events/"
        assert conf.shared_files[0].local_path == "events/guide.md"

    def test_absolute_local_paths_not_prefixed(self, fake_project):
        root, shared_dir = fake_project
        config = {
            "projects": {
                "myproj": {
                    "source_repo": {"url": "https://example.com/repo.git"},
                    "shared_files": [
                        {"remote_path": "doc.md", "local_path": "/src/docs/doc.md", "action": "get"}
                    ],
                },
            },
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")

        conf = load_config(root, project="myproj")
        assert conf.shared_files[0].local_path == "/src/docs/doc.md"

    def test_legacy_format_does_not_prefix_local_paths(self, configured_project):
        root, _ = configured_project
        conf = load_config(root)
        # Legacy format should not alter local_path
        assert conf.shared_files[0].local_path == "python_gitignore.txt"


class TestValidateProjectName:
    def test_valid_names_pass(self):
        for name in ["auth", "agent-coder", "tlc_core", "my.project", "A1"]:
            validate_project_name(name)  # should not raise

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError, match="Invalid project name"):
            validate_project_name("")

    def test_rejects_leading_hyphen(self):
        with pytest.raises(ValueError, match="Invalid project name"):
            validate_project_name("-bad")

    def test_rejects_leading_dot(self):
        with pytest.raises(ValueError, match="Invalid project name"):
            validate_project_name(".hidden")

    def test_rejects_slashes(self):
        with pytest.raises(ValueError, match="Invalid project name"):
            validate_project_name("org/repo")

    def test_rejects_spaces(self):
        with pytest.raises(ValueError, match="Invalid project name"):
            validate_project_name("my project")

    def test_rejects_special_characters(self):
        for name in ["proj@1", "proj!x", "proj:1", "proj<x>"]:
            with pytest.raises(ValueError, match="Invalid project name"):
                validate_project_name(name)

    def test_invalid_name_in_config_raises_on_load(self, fake_project):
        root, shared_dir = fake_project
        config = {
            "projects": {
                "../escape": {
                    "source_repo": {"url": "https://example.com/repo.git"},
                },
            },
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")

        with pytest.raises(ValueError, match="Invalid project name"):
            load_config(root, project="../escape")


class TestListProjects:
    def test_lists_all_projects_sorted(self, fake_project):
        root, shared_dir = fake_project
        config = {
            "projects": {
                "events": {"source_repo": {"url": "https://example.com/events.git", "branch": "dev"}, "mode": "central"},
                "auth": {"source_repo": {"url": "https://example.com/auth.git"}, "mode": "central"},
                "agent": {"source_repo": {"url": "https://example.com/agent.git"}},
            },
            "default_project": "agent",
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")

        result = list_projects(root)
        assert len(result) == 3
        # Sorted alphabetically
        assert result[0]["name"] == "agent (default)"
        assert result[1]["name"] == "auth"
        assert result[2]["name"] == "events"
        # Fields populated correctly
        assert result[0]["url"] == "https://example.com/agent.git"
        assert result[0]["branch"] == "main"
        assert result[0]["mode"] == "local"
        assert result[2]["branch"] == "dev"
        assert result[2]["mode"] == "central"

    def test_returns_empty_for_legacy_config(self, configured_project):
        root, _ = configured_project
        assert list_projects(root) == []

    def test_raises_when_no_config(self, fake_project):
        root, _ = fake_project
        with pytest.raises(FileNotFoundError):
            list_projects(root)
