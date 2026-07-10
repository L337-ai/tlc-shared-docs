"""Tests for git operations."""

from __future__ import annotations

import pytest

from tlc_shared_docs.git_ops import (
    GitError,
    _inject_pat,
    check_ignored,
    cleanup,
    list_remote_files,
    read_file_from_clone,
    sparse_checkout_files,
)


class TestInjectPat:
    """Unit tests for _inject_pat — no network required."""

    def test_injects_pat_into_plain_https_url(self, monkeypatch):
        monkeypatch.setenv("GH_PAT", "ghp_token123")
        result = _inject_pat("https://github.com/org/repo.git")
        assert result == "https://ghp_token123@github.com/org/repo.git"

    def test_noop_when_gh_pat_not_set(self, monkeypatch):
        monkeypatch.delenv("GH_PAT", raising=False)
        url = "https://github.com/org/repo.git"
        assert _inject_pat(url) == url

    def test_noop_for_ssh_url(self, monkeypatch):
        monkeypatch.setenv("GH_PAT", "ghp_token123")
        url = "git@github.com:org/repo.git"
        assert _inject_pat(url) == url

    def test_noop_when_credentials_already_embedded(self, monkeypatch):
        monkeypatch.setenv("GH_PAT", "ghp_token123")
        url = "https://existing_user@github.com/org/repo.git"
        assert _inject_pat(url) == url

    def test_noop_when_user_and_password_embedded(self, monkeypatch):
        monkeypatch.setenv("GH_PAT", "ghp_token123")
        url = "https://user:pass@github.com/org/repo.git"
        assert _inject_pat(url) == url


class TestCheckIgnored:
    """Unit tests for check_ignored — local git repo, no network."""

    def _init_repo(self, tmp_path):
        from git import Repo
        repo = Repo.init(tmp_path)
        repo.close()
        return tmp_path

    def test_ignored_file_reported_with_source(self, tmp_path):
        root = self._init_repo(tmp_path)
        (root / ".gitignore").write_text("secret*\n", encoding="utf-8")
        (root / "secret.md").write_text("s", encoding="utf-8")
        (root / "plain.md").write_text("p", encoding="utf-8")

        result = check_ignored(root, ["secret.md", "plain.md"])
        assert result == {"secret.md": ".gitignore"}

    def test_negation_pattern_not_reported_ignored(self, tmp_path):
        root = self._init_repo(tmp_path)
        (root / ".gitignore").write_text("secret*\n!secret-keep.md\n", encoding="utf-8")
        (root / "secret-keep.md").write_text("k", encoding="utf-8")

        result = check_ignored(root, ["secret-keep.md"])
        assert "secret-keep.md" not in result

    def test_nested_gitignore_source_is_relative(self, tmp_path):
        root = self._init_repo(tmp_path)
        sub = root / "docs"
        sub.mkdir()
        (sub / ".gitignore").write_text("*.log\n", encoding="utf-8")
        (sub / "debug.log").write_text("x", encoding="utf-8")

        result = check_ignored(root, ["docs/debug.log"])
        assert result == {"docs/debug.log": "docs/.gitignore"}

    def test_no_ignored_paths_returns_empty(self, tmp_path):
        root = self._init_repo(tmp_path)
        (root / "plain.md").write_text("p", encoding="utf-8")
        assert check_ignored(root, ["plain.md"]) == {}

    def test_not_a_git_repo_returns_empty(self, tmp_path):
        # Bare .git marker directory (like the fake_project fixture)
        (tmp_path / ".git").mkdir()
        (tmp_path / "file.md").write_text("x", encoding="utf-8")
        assert check_ignored(tmp_path, ["file.md"]) == {}

    def test_empty_path_list_returns_empty(self, tmp_path):
        root = self._init_repo(tmp_path)
        assert check_ignored(root, []) == {}


# Real public repo for integration tests
REPO_URL = "https://github.com/github/gitignore.git"
BRANCH = "main"
KNOWN_FILE = "Python.gitignore"


@pytest.mark.integration
class TestSparseCheckout:
    def test_sparse_checkout_fetches_file(self):
        clone_dir, repo = sparse_checkout_files(REPO_URL, BRANCH, [KNOWN_FILE])
        try:
            content = read_file_from_clone(clone_dir, KNOWN_FILE)
            # Python.gitignore should contain common Python ignores
            text = content.decode("utf-8")
            assert "__pycache__" in text
        finally:
            cleanup(clone_dir)

    def test_sparse_checkout_missing_file(self):
        clone_dir, repo = sparse_checkout_files(REPO_URL, BRANCH, ["nonexistent_xyz.txt"])
        try:
            with pytest.raises(FileNotFoundError):
                read_file_from_clone(clone_dir, "nonexistent_xyz.txt")
        finally:
            cleanup(clone_dir)

    def test_sparse_checkout_bad_url(self):
        with pytest.raises(GitError):
            sparse_checkout_files(
                "https://github.com/nonexistent/repo_that_does_not_exist.git",
                "main",
                ["file.txt"],
            )


@pytest.mark.integration
class TestListRemoteFiles:
    def test_glob_star(self):
        """*.gitignore should match top-level gitignore files."""
        matched = list_remote_files(REPO_URL, BRANCH, "*.gitignore")
        assert "Python.gitignore" in matched
        assert "Go.gitignore" in matched
        assert len(matched) > 10  # there are many

    def test_glob_subdir(self):
        """community/**/* should match files under community/."""
        matched = list_remote_files(REPO_URL, BRANCH, "community/**/*")
        assert len(matched) > 0
        assert all(m.startswith("community/") for m in matched)

    def test_glob_no_match(self):
        """A pattern matching nothing returns an empty list."""
        matched = list_remote_files(REPO_URL, BRANCH, "zzz_nonexistent_pattern_*.xyz")
        assert matched == []

    def test_glob_specific_extension(self):
        """Global/**/*.gitignore should find community templates."""
        matched = list_remote_files(REPO_URL, BRANCH, "Global/*.gitignore")
        assert len(matched) > 0
        assert all(m.startswith("Global/") for m in matched)
