"""Low-level Git helpers using GitPython (and the ``git`` CLI it wraps)."""

from __future__ import annotations

import fnmatch
import shutil
import tempfile
from pathlib import Path
from typing import List

from git import Repo, GitCommandError


class GitError(RuntimeError):
    """Raised when a git operation fails."""


def _tmp_clone_dir() -> Path:
    """Return a fresh temporary directory for cloning."""
    return Path(tempfile.mkdtemp(prefix="tlc_shared_docs_"))


def list_remote_files(
    url: str,
    branch: str,
    pattern: str,
) -> List[str]:
    """Return remote file paths matching a glob *pattern*.

    Uses a treeless clone (``--filter=tree:0``) so only the tree metadata
    is fetched — no file blobs are downloaded.
    """
    clone_dir = _tmp_clone_dir()
    try:
        repo = Repo.init(clone_dir)
        repo.git.remote("add", "origin", url)
        repo.git.fetch("origin", branch, depth=1, filter="tree:0")

        # List every file path in the tree
        output = repo.git.ls_tree("-r", "--name-only", f"origin/{branch}")
        all_files = output.splitlines() if output else []

        # Filter with fnmatch (supports *, ?, [seq], **)
        matched = [f for f in all_files if fnmatch.fnmatch(f, pattern)]
        return matched
    except GitCommandError as exc:
        raise GitError(f"Failed to list files from {url}: {exc}") from exc
    finally:
        shutil.rmtree(clone_dir, ignore_errors=True)


def sparse_checkout_files(
    url: str,
    branch: str,
    file_paths: List[str],
) -> tuple[Path, Repo]:
    """Clone *url* at *branch* with a **sparse checkout** containing only
    *file_paths*.  Returns ``(clone_dir, Repo)``."""
    clone_dir = _tmp_clone_dir()
    try:
        # Initialise an empty repo and configure sparse-checkout
        repo = Repo.init(clone_dir)
        repo.git.remote("add", "origin", url)
        repo.git.config("core.sparseCheckout", "true")

        # Write the sparse-checkout patterns
        sparse_file = Path(repo.git_dir) / "info" / "sparse-checkout"
        sparse_file.parent.mkdir(parents=True, exist_ok=True)
        sparse_file.write_text("\n".join(file_paths) + "\n", encoding="utf-8")

        # Fetch only the requested branch (shallow, single-branch)
        repo.git.fetch("origin", branch, depth=1)
        repo.git.checkout(f"origin/{branch}", b=branch)

        return clone_dir, repo
    except GitCommandError as exc:
        shutil.rmtree(clone_dir, ignore_errors=True)
        raise GitError(f"Failed to sparse-checkout from {url}: {exc}") from exc


def read_file_from_clone(clone_dir: Path, remote_path: str) -> bytes:
    """Read a single file out of a sparse clone."""
    target = clone_dir / remote_path
    if not target.exists():
        raise FileNotFoundError(f"File not found in clone: {remote_path}")
    return target.read_bytes()


def push_files(
    url: str,
    branch: str,
    file_map: dict[str, bytes],
    commit_message: str,
    force: bool = False,
) -> None:
    """Clone *url*, write *file_map* ``{remote_path: content}``, commit, and
    push to *branch*.

    If *force* is ``True`` the push uses ``--force``.
    """
    clone_dir = _tmp_clone_dir()
    try:
        # Shallow clone with the target branch checked out
        repo = Repo.init(clone_dir)
        repo.git.remote("add", "origin", url)
        repo.git.fetch("origin", branch, depth=1)
        repo.git.checkout(f"origin/{branch}", b=branch)

        changed = False
        for remote_path, content in file_map.items():
            dest = clone_dir / remote_path
            dest.parent.mkdir(parents=True, exist_ok=True)

            # Check if file already exists with same content
            if dest.exists() and dest.read_bytes() == content:
                continue

            dest.write_bytes(content)
            repo.index.add([remote_path])
            changed = True

        if not changed:
            return  # nothing to push

        repo.index.commit(commit_message)

        push_args = ["origin", branch]
        if force:
            push_args.insert(0, "--force")
        repo.git.push(*push_args)
    except GitCommandError as exc:
        raise GitError(f"Failed to push to {url}: {exc}") from exc
    finally:
        shutil.rmtree(clone_dir, ignore_errors=True)


def check_remote_unchanged(
    url: str,
    branch: str,
    remote_path: str,
    local_content: bytes,
) -> bool:
    """Return ``True`` if the remote file matches *local_content*
    (i.e. no remote changes since last pull)."""
    clone_dir = _tmp_clone_dir()
    try:
        clone_dir, _repo = sparse_checkout_files(url, branch, [remote_path])
        remote_file = clone_dir / remote_path
        if not remote_file.exists():
            # File doesn't exist on remote yet — safe to push
            return True
        return remote_file.read_bytes() == local_content
    except GitError:
        raise
    finally:
        shutil.rmtree(clone_dir, ignore_errors=True)


def cleanup(clone_dir: Path) -> None:
    """Remove a temporary clone directory."""
    shutil.rmtree(clone_dir, ignore_errors=True)
