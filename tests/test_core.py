"""Tests for the core get/push logic."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tlc_shared_docs.core import _resolve_config, get_files, push_files
from tlc_shared_docs.config import SharedConfig, SharedFile, SourceRepo


class TestGetFilesDryRun:
    @patch("tlc_shared_docs.core.git_ops.get_remote_blob_shas", return_value={"Python.gitignore": "abc123"})
    def test_dry_run_lists_files(self, mock_shas, configured_project):
        root, _ = configured_project
        messages = get_files(project_root=root, dry_run=True)
        assert any("[dry-run]" in m and "Python.gitignore" in m for m in messages)

    def test_no_get_files(self, fake_project):
        root, shared_dir = fake_project
        config = {
            "source_repo": {"url": "https://example.com/repo.git"},
            "shared_files": [
                {"remote_path": "a.md", "local_path": "a.md", "action": "push"}
            ],
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")
        messages = get_files(project_root=root)
        assert "No files with action=get" in messages[0]


class TestGetFilesIntegration:
    @pytest.mark.integration
    def test_get_fetches_real_file(self, configured_project):
        root, shared_dir = configured_project
        messages = get_files(project_root=root)
        assert any("OK" in m for m in messages)

        # Verify the file was actually written
        fetched = shared_dir / "python_gitignore.txt"
        assert fetched.exists()
        content = fetched.read_text(encoding="utf-8")
        assert "__pycache__" in content


class TestGetFilesGlobMocked:
    @patch("tlc_shared_docs.core.git_ops")
    def test_glob_expands_to_concrete_files(self, mock_git_ops, fake_project):
        root, shared_dir = fake_project
        config = {
            "source_repo": {"url": "https://example.com/repo.git", "branch": "main"},
            "shared_files": [
                {"remote_path": "stories/**/*", "local_path": "stories", "action": "get"}
            ],
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")

        # Mock list_remote_files to return two matches
        mock_git_ops.list_remote_files.return_value = [
            "stories/chapter1/intro.md",
            "stories/chapter2/outro.md",
        ]
        # Mock SHA lookup — new SHAs so files are not skipped
        mock_git_ops.get_remote_blob_shas.return_value = {
            "stories/chapter1/intro.md": "sha1",
            "stories/chapter2/outro.md": "sha2",
        }
        # Mock sparse checkout and file reads
        mock_clone_dir = MagicMock()
        mock_git_ops.sparse_checkout_files.return_value = (mock_clone_dir, MagicMock())
        mock_git_ops.read_file_from_clone.return_value = b"# Content"
        mock_git_ops.cleanup = MagicMock()

        messages = get_files(project_root=root)
        assert any("matched 2 file(s)" in m for m in messages)
        assert mock_git_ops.sparse_checkout_files.called

    @patch("tlc_shared_docs.core.git_ops")
    def test_glob_dry_run(self, mock_git_ops, fake_project):
        root, shared_dir = fake_project
        config = {
            "source_repo": {"url": "https://example.com/repo.git", "branch": "main"},
            "shared_files": [
                {"remote_path": "Global/*.gitignore", "local_path": "global_ignores", "action": "get"}
            ],
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")

        mock_git_ops.list_remote_files.return_value = ["Global/Vim.gitignore", "Global/macOS.gitignore"]
        mock_git_ops.get_remote_blob_shas.return_value = {
            "Global/Vim.gitignore": "sha1",
            "Global/macOS.gitignore": "sha2",
        }

        messages = get_files(project_root=root, dry_run=True)
        assert any("[dry-run]" in m for m in messages)
        assert any("Vim.gitignore" in m for m in messages)

    @patch("tlc_shared_docs.core.git_ops")
    def test_glob_no_matches(self, mock_git_ops, fake_project):
        root, shared_dir = fake_project
        config = {
            "source_repo": {"url": "https://example.com/repo.git", "branch": "main"},
            "shared_files": [
                {"remote_path": "nonexistent/**/*", "local_path": "nope", "action": "get"}
            ],
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")

        mock_git_ops.list_remote_files.return_value = []

        messages = get_files(project_root=root)
        assert any("WARNING" in m and "No remote files matched" in m for m in messages)

    @patch("tlc_shared_docs.core.git_ops")
    def test_glob_preserves_relative_structure(self, mock_git_ops, fake_project):
        """Files under stories/a/b.md with local_path='mystories' should land at mystories/a/b.md."""
        root, shared_dir = fake_project
        config = {
            "source_repo": {"url": "https://example.com/repo.git", "branch": "main"},
            "shared_files": [
                {"remote_path": "stories/**/*", "local_path": "mystories", "action": "get"}
            ],
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")

        mock_git_ops.list_remote_files.return_value = ["stories/a/b.md"]
        mock_git_ops.get_remote_blob_shas.return_value = {"stories/a/b.md": "sha1"}
        mock_clone_dir = MagicMock()
        mock_git_ops.sparse_checkout_files.return_value = (mock_clone_dir, MagicMock())
        mock_git_ops.read_file_from_clone.return_value = b"hello"
        mock_git_ops.cleanup = MagicMock()

        messages = get_files(project_root=root)
        # The file should be written to shared_dir / mystories / a / b.md
        expected = shared_dir / "mystories" / "a" / "b.md"
        assert expected.exists()
        assert expected.read_bytes() == b"hello"


class TestGetFilesGlobIntegration:
    @pytest.mark.integration
    def test_glob_get_from_real_repo(self, fake_project):
        """Fetch Global/*.gitignore from github/gitignore."""
        root, shared_dir = fake_project
        config = {
            "source_repo": {
                "url": "https://github.com/github/gitignore.git",
                "branch": "main",
            },
            "shared_files": [
                {"remote_path": "Global/*.gitignore", "local_path": "global_ignores", "action": "get"}
            ],
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")

        messages = get_files(project_root=root)
        assert any("matched" in m for m in messages)
        assert any("OK" in m for m in messages)

        # Should have fetched multiple files into global_ignores/
        dest = shared_dir / "global_ignores"
        assert dest.is_dir()
        fetched = list(dest.glob("*.gitignore"))
        assert len(fetched) > 5  # there are many Global/*.gitignore files


class TestSkipUnchanged:
    """Tests for SHA-based skip logic on get."""

    @patch("tlc_shared_docs.core.git_ops.get_remote_blob_shas")
    @patch("tlc_shared_docs.core.git_ops.sparse_checkout_files")
    @patch("tlc_shared_docs.core.git_ops.read_file_from_clone")
    @patch("tlc_shared_docs.core.git_ops.cleanup")
    def test_skips_unchanged_file(self, mock_cleanup, mock_read, mock_sparse, mock_shas, fake_project):
        root, shared_dir = fake_project
        config = {
            "source_repo": {"url": "https://example.com/repo.git", "branch": "main"},
            "shared_files": [
                {"remote_path": "doc.md", "local_path": "doc.md", "action": "get"}
            ],
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")

        # Write the local file and a matching hash
        (shared_dir / "doc.md").write_text("existing content")
        from tlc_shared_docs.config import save_hashes
        save_hashes(root, {"doc.md": "abc123"})

        # Remote SHA matches stored hash
        mock_shas.return_value = {"doc.md": "abc123"}

        messages = get_files(project_root=root)
        assert any("SKIP (unchanged)" in m for m in messages)
        # Should NOT have called sparse_checkout since nothing needed
        mock_sparse.assert_not_called()

    @patch("tlc_shared_docs.core.git_ops.get_remote_blob_shas")
    @patch("tlc_shared_docs.core.git_ops.sparse_checkout_files")
    @patch("tlc_shared_docs.core.git_ops.read_file_from_clone", return_value=b"new content")
    @patch("tlc_shared_docs.core.git_ops.cleanup")
    def test_fetches_when_sha_differs(self, mock_cleanup, mock_read, mock_sparse, mock_shas, fake_project):
        root, shared_dir = fake_project
        config = {
            "source_repo": {"url": "https://example.com/repo.git", "branch": "main"},
            "shared_files": [
                {"remote_path": "doc.md", "local_path": "doc.md", "action": "get"}
            ],
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")

        # Old hash stored, new SHA on remote
        from tlc_shared_docs.config import save_hashes
        save_hashes(root, {"doc.md": "old_sha"})

        mock_shas.return_value = {"doc.md": "new_sha"}
        mock_sparse.return_value = (MagicMock(), MagicMock())

        messages = get_files(project_root=root)
        assert any("OK" in m for m in messages)
        mock_sparse.assert_called_once()

    @patch("tlc_shared_docs.core.git_ops.get_remote_blob_shas")
    @patch("tlc_shared_docs.core.git_ops.sparse_checkout_files")
    @patch("tlc_shared_docs.core.git_ops.read_file_from_clone", return_value=b"content")
    @patch("tlc_shared_docs.core.git_ops.cleanup")
    def test_fetches_when_local_file_missing(self, mock_cleanup, mock_read, mock_sparse, mock_shas, fake_project):
        """Even if SHA matches, fetch if the local file doesn't exist."""
        root, shared_dir = fake_project
        config = {
            "source_repo": {"url": "https://example.com/repo.git", "branch": "main"},
            "shared_files": [
                {"remote_path": "doc.md", "local_path": "doc.md", "action": "get"}
            ],
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")

        from tlc_shared_docs.config import save_hashes
        save_hashes(root, {"doc.md": "abc123"})
        # SHA matches but local file doesn't exist

        mock_shas.return_value = {"doc.md": "abc123"}
        mock_sparse.return_value = (MagicMock(), MagicMock())

        messages = get_files(project_root=root)
        assert any("OK" in m for m in messages)
        mock_sparse.assert_called_once()

    @patch("tlc_shared_docs.core.git_ops.get_remote_blob_shas")
    @patch("tlc_shared_docs.core.git_ops.sparse_checkout_files")
    @patch("tlc_shared_docs.core.git_ops.read_file_from_clone", return_value=b"content")
    @patch("tlc_shared_docs.core.git_ops.cleanup")
    def test_saves_hashes_after_fetch(self, mock_cleanup, mock_read, mock_sparse, mock_shas, fake_project):
        root, shared_dir = fake_project
        config = {
            "source_repo": {"url": "https://example.com/repo.git", "branch": "main"},
            "shared_files": [
                {"remote_path": "doc.md", "local_path": "doc.md", "action": "get"}
            ],
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")

        mock_shas.return_value = {"doc.md": "new_sha"}
        mock_sparse.return_value = (MagicMock(), MagicMock())

        get_files(project_root=root)

        from tlc_shared_docs.config import load_hashes
        hashes = load_hashes(root)
        assert hashes["doc.md"] == "new_sha"

    @patch("tlc_shared_docs.core.git_ops.get_remote_blob_shas")
    def test_skip_unchanged_in_dry_run(self, mock_shas, fake_project):
        root, shared_dir = fake_project
        config = {
            "source_repo": {"url": "https://example.com/repo.git", "branch": "main"},
            "shared_files": [
                {"remote_path": "a.md", "local_path": "a.md", "action": "get"},
                {"remote_path": "b.md", "local_path": "b.md", "action": "get"},
            ],
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")

        # a.md is unchanged, b.md is new
        (shared_dir / "a.md").write_text("old")
        from tlc_shared_docs.config import save_hashes
        save_hashes(root, {"a.md": "sha_a"})

        mock_shas.return_value = {"a.md": "sha_a", "b.md": "sha_b"}

        messages = get_files(project_root=root, dry_run=True)
        assert any("SKIP (unchanged)" in m and "a.md" in m for m in messages)
        assert any("[dry-run]" in m and "b.md" in m for m in messages)


class TestPushFilesDryRun:
    def test_dry_run_lists_files(self, fake_project):
        root, shared_dir = fake_project
        config = {
            "source_repo": {"url": "https://example.com/repo.git", "branch": "main"},
            "shared_files": [
                {"remote_path": "docs/guide.md", "local_path": "guide.md", "action": "push"}
            ],
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")
        messages = push_files(project_root=root, dry_run=True)
        assert len(messages) == 1
        assert "[dry-run]" in messages[0]
        assert "guide.md" in messages[0]


class TestPushFilesMocked:
    def test_push_missing_local_file(self, fake_project):
        root, shared_dir = fake_project
        config = {
            "source_repo": {"url": "https://example.com/repo.git", "branch": "main"},
            "shared_files": [
                {"remote_path": "docs/guide.md", "local_path": "guide.md", "action": "push"}
            ],
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")
        messages = push_files(project_root=root)
        assert any("WARNING" in m for m in messages)
        assert any("missing" in m.lower() for m in messages)

    @patch("tlc_shared_docs.core.git_ops")
    def test_push_calls_git_push(self, mock_git_ops, fake_project):
        root, shared_dir = fake_project
        config = {
            "source_repo": {"url": "https://example.com/repo.git", "branch": "main"},
            "shared_files": [
                {"remote_path": "docs/guide.md", "local_path": "guide.md", "action": "push"}
            ],
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")

        # Create the local file
        (shared_dir / "guide.md").write_text("# Guide\nHello", encoding="utf-8")

        # Mock the sparse checkout for conflict checking
        mock_clone_dir = MagicMock()
        mock_clone_dir.__truediv__ = lambda self, x: Path("/fake") / x
        mock_git_ops.sparse_checkout_files.return_value = (mock_clone_dir, MagicMock())
        mock_git_ops.cleanup = MagicMock()
        mock_git_ops.push_files = MagicMock()

        messages = push_files(project_root=root, force=True)
        mock_git_ops.push_files.assert_called_once()
        assert any("OK" in m for m in messages)

    def test_no_push_files(self, configured_project):
        root, _ = configured_project
        # Default sample config only has action=get files
        messages = push_files(project_root=root)
        assert "No files with action=push" in messages[0]


class TestCLI:
    @patch("tlc_shared_docs.core.git_ops.get_remote_blob_shas", return_value={"Python.gitignore": "abc123"})
    def test_get_dry_run_via_cli(self, mock_shas, configured_project):
        """Test the CLI entry point for get --dry-run."""
        from tlc_shared_docs.cli import main

        root, _ = configured_project

        # Patch find_project_root to use our temp dir
        with patch("tlc_shared_docs.core.cfg.find_project_root", return_value=root):
            # Should not raise
            main(["get", "--dry-run"])

    def test_no_command_exits(self):
        from tlc_shared_docs.cli import main
        with pytest.raises(SystemExit):
            main([])

    def test_version_flag(self, capsys):
        from tlc_shared_docs.cli import main
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0


class TestResolveConfigCentral:
    """Tests for central mode config resolution."""

    def _make_conf(self, mode="central", url="https://example.com/shared.git", shared_files=None):
        return SharedConfig(
            source_repo=SourceRepo(url=url, branch="main"),
            shared_files=shared_files or [],
            mode=mode,
        )

    @patch("tlc_shared_docs.core.cfg.detect_repo_identity", return_value="myorg/myapp")
    @patch("tlc_shared_docs.core.git_ops.fetch_single_file")
    def test_central_fetches_config(self, mock_fetch, mock_detect, tmp_path):
        central_data = {
            "shared_files": [
                {"remote_path": "docs/intro.md", "local_path": "intro.md", "action": "get"}
            ]
        }
        mock_fetch.return_value = json.dumps(central_data).encode()

        conf = self._make_conf()
        resolved, msgs = _resolve_config(tmp_path, conf)

        mock_fetch.assert_called_once_with(
            "https://example.com/shared.git", "main", ".configs/myorg/myapp.json"
        )
        assert resolved.mode == "central"
        assert len(resolved.shared_files) == 1
        assert resolved.shared_files[0].remote_path == "docs/intro.md"
        assert any("Central mode" in m for m in msgs)

    @patch("tlc_shared_docs.core.cfg.detect_repo_identity", return_value="myorg/myapp")
    @patch("tlc_shared_docs.core.git_ops.fetch_single_file")
    def test_central_warns_local_files_ignored(self, mock_fetch, mock_detect, tmp_path):
        """When local shared.json has shared_files AND mode=central, warn."""
        central_data = {
            "shared_files": [
                {"remote_path": "a.md", "local_path": "a.md", "action": "get"}
            ]
        }
        mock_fetch.return_value = json.dumps(central_data).encode()

        conf = self._make_conf(shared_files=[
            SharedFile(remote_path="local.md", local_path="local.md", action="get")
        ])
        resolved, msgs = _resolve_config(tmp_path, conf)

        assert any("WARNING" in m and "Central config takes precedence" in m for m in msgs)
        # Central files win, local files are not in the result
        assert len(resolved.shared_files) == 1
        assert resolved.shared_files[0].remote_path == "a.md"

    @patch("tlc_shared_docs.core.cfg.detect_repo_identity", return_value="myorg/myapp")
    @patch("tlc_shared_docs.core.git_ops.fetch_single_file")
    def test_central_config_not_found_raises(self, mock_fetch, mock_detect, tmp_path):
        mock_fetch.return_value = None

        conf = self._make_conf()
        with pytest.raises(FileNotFoundError, match="Central config not found"):
            _resolve_config(tmp_path, conf)

    def test_local_mode_skips_central(self, tmp_path):
        """Local mode should pass through unchanged."""
        conf = self._make_conf(mode="local")
        resolved, msgs = _resolve_config(tmp_path, conf)
        assert resolved is conf
        assert msgs == []

    @patch("tlc_shared_docs.core.cfg.detect_repo_identity", return_value="myorg/myapp")
    @patch("tlc_shared_docs.core.git_ops.fetch_single_file")
    def test_cli_central_url_overrides_mode(self, mock_fetch, mock_detect, tmp_path):
        """--central CLI flag should activate central mode even if mode=local."""
        central_data = {
            "shared_files": [
                {"remote_path": "x.md", "local_path": "x.md", "action": "get"}
            ]
        }
        mock_fetch.return_value = json.dumps(central_data).encode()

        conf = self._make_conf(mode="local")
        resolved, msgs = _resolve_config(
            tmp_path, conf, central_url="https://override.com/docs.git"
        )

        mock_fetch.assert_called_once_with(
            "https://override.com/docs.git", "main", ".configs/myorg/myapp.json"
        )
        assert resolved.mode == "central"

    @patch("tlc_shared_docs.core.git_ops.get_remote_blob_shas", return_value={"guide.md": "sha1"})
    @patch("tlc_shared_docs.core.cfg.detect_repo_identity", return_value="myorg/myapp")
    @patch("tlc_shared_docs.core.git_ops.fetch_single_file")
    def test_central_get_dry_run(self, mock_fetch, mock_detect, mock_shas, fake_project):
        """Central mode + get --dry-run should show the resolved files."""
        root, shared_dir = fake_project
        config = {
            "mode": "central",
            "source_repo": {"url": "https://example.com/shared.git", "branch": "main"},
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")

        central_data = {
            "shared_files": [
                {"remote_path": "guide.md", "local_path": "guide.md", "action": "get"}
            ]
        }
        mock_fetch.return_value = json.dumps(central_data).encode()

        messages = get_files(project_root=root, dry_run=True)
        assert any("[dry-run]" in m for m in messages)
        assert any("guide.md" in m for m in messages)

    @patch("tlc_shared_docs.core.cfg.detect_repo_identity", return_value="myorg/myapp")
    @patch("tlc_shared_docs.core.git_ops.fetch_single_file")
    def test_central_push_dry_run(self, mock_fetch, mock_detect, fake_project):
        """Central mode + push --dry-run should show the resolved files."""
        root, shared_dir = fake_project
        config = {
            "mode": "central",
            "source_repo": {"url": "https://example.com/shared.git", "branch": "main"},
        }
        (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")

        central_data = {
            "shared_files": [
                {"remote_path": "guide.md", "local_path": "guide.md", "action": "push"}
            ]
        }
        mock_fetch.return_value = json.dumps(central_data).encode()

        messages = push_files(project_root=root, dry_run=True)
        assert any("[dry-run]" in m for m in messages)
        assert any("guide.md" in m for m in messages)
