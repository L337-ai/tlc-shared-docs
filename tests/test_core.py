"""Tests for the core get/push logic."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tlc_shared_docs.core import get_files, push_files


class TestGetFilesDryRun:
    def test_dry_run_lists_files(self, configured_project):
        root, _ = configured_project
        messages = get_files(project_root=root, dry_run=True)
        assert len(messages) == 1
        assert "[dry-run]" in messages[0]
        assert "Python.gitignore" in messages[0]

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
    def test_get_dry_run_via_cli(self, configured_project):
        """Test the CLI entry point for get --dry-run."""
        from tlc_shared_docs.cli import main
        import sys

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
