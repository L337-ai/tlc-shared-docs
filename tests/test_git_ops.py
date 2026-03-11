"""Tests for git operations."""

from __future__ import annotations

import pytest

from tlc_shared_docs.git_ops import (
    GitError,
    cleanup,
    list_remote_files,
    read_file_from_clone,
    sparse_checkout_files,
)

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
