"""Tests for git operations."""

from __future__ import annotations

import pytest

from tlc_shared_docs.git_ops import (
    GitError,
    cleanup,
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
