"""Low-level Git helpers using GitPython (and the ``git`` CLI it wraps)."""

from __future__ import annotations

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
    is fetched -- no file blobs are downloaded.
    """
    clone_dir = _tmp_clone_dir()
    try:
        repo = Repo.init(clone_dir)
        repo.git.remote("add", "origin", url)

        # Treeless fetch: downloads tree objects but no blobs
        repo.git.fetch("origin", branch, depth=1, filter="tree:0")

        # List every file path in the tree
        output = repo.git.ls_tree("-r", "--name-only", f"origin/{branch}")
        all_files = output.splitlines() if output else []

        # Filter with our glob_match (supports *, ?, [seq], **)
        from tlc_shared_docs.config import glob_match
        matched = [f for f in all_files if glob_match(f, pattern)]
        return matched
    except GitCommandError as exc:
        raise GitError(f"Failed to list files from {url}: {exc}") from exc
    finally:
        shutil.rmtree(clone_dir, ignore_errors=True)


def get_remote_blob_shas(
    url: str,
    branch: str,
    file_paths: List[str],
) -> dict[str, str]:
    """Return ``{file_path: blob_sha}`` for each of *file_paths* that exists
    on *branch* of *url*.

    Uses a treeless fetch so no file content is downloaded -- only
    tree metadata needed to read the blob SHA per path.
    """
    clone_dir = _tmp_clone_dir()
    try:
        repo = Repo.init(clone_dir)
        repo.git.remote("add", "origin", url)
        repo.git.fetch("origin", branch, depth=1, filter="tree:0")

        # Parse full ls-tree output: "<mode> <type> <sha>\t<path>"
        output = repo.git.ls_tree("-r", f"origin/{branch}")
        if not output:
            return {}

        sha_map: dict[str, str] = {}
        wanted = set(file_paths)
        for line in output.splitlines():
            parts = line.split(None, 3)  # mode, type, sha, path
            if len(parts) == 4:
                path = parts[3]
                if path in wanted:
                    sha_map[path] = parts[2]
        return sha_map
    except GitCommandError as exc:
        raise GitError(f"Failed to get blob SHAs from {url}: {exc}") from exc
    finally:
        shutil.rmtree(clone_dir, ignore_errors=True)


def sparse_checkout_files(
    url: str,
    branch: str,
    file_paths: List[str],
) -> tuple[Path, Repo]:
    """Clone *url* at *branch* with a **sparse checkout** containing only
    *file_paths*.  Returns ``(clone_dir, Repo)``.

    Depth=1 avoids fetching full history -- we only need latest content.
    """
    clone_dir = _tmp_clone_dir()
    try:
        # Initialise an empty repo and configure sparse-checkout
        repo = Repo.init(clone_dir)
        repo.git.remote("add", "origin", url)
        repo.git.config("core.sparseCheckout", "true")

        # Write the sparse-checkout patterns so only requested files appear
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
    verbose: bool = False,
    _print: object = None,
) -> List[str]:
    """Clone *url*, write *file_map* ``{remote_path: content}``, commit, and
    push to *branch*.

    If *force* is ``True`` the push uses ``--force``.

    Returns a list of remote paths that were actually written (i.e., differed
    from what was already on the remote). An empty list means nothing changed.
    """
    def vlog(msg: str) -> None:
        if verbose and _print:
            _print(msg)

    clone_dir = _tmp_clone_dir()
    try:
        vlog(f"[verbose] Clone dir: {clone_dir}")

        # Shallow clone with the target branch checked out
        repo = Repo.init(clone_dir)
        repo.git.remote("add", "origin", url)
        vlog(f"[verbose] Fetching {branch} from {url} (depth=1)...")
        repo.git.fetch("origin", branch, depth=1)
        repo.git.checkout(f"origin/{branch}", b=branch)

        # Get the HEAD commit of the cloned branch
        head_sha = repo.git.rev_parse("HEAD")
        vlog(f"[verbose] Remote HEAD: {head_sha}")

        # Read existing blob SHAs from the remote tree
        existing_shas: dict[str, str] = {}
        try:
            tree_output = repo.git.ls_tree("-r", f"origin/{branch}")
            for line in tree_output.splitlines():
                parts = line.split(None, 3)
                if len(parts) == 4:
                    existing_shas[parts[3]] = parts[2]
        except GitCommandError:
            pass

        vlog(f"[verbose] Remote tree has {len(existing_shas)} file(s)")

        actually_pushed: List[str] = []
        for remote_path, content in file_map.items():
            dest = clone_dir / remote_path
            dest.parent.mkdir(parents=True, exist_ok=True)

            # Compute the blob SHA git would assign to the new content.
            # Write to a temp file because GitPython can't pipe binary to stdin.
            hash_tmp = clone_dir / ".hash_tmp"
            hash_tmp.write_bytes(content)
            new_sha = repo.git.hash_object(str(hash_tmp))
            hash_tmp.unlink()
            old_sha = existing_shas.get(remote_path)

            vlog(f"[verbose] {remote_path}: old_sha={old_sha} new_sha={new_sha} local_bytes={len(content)}")

            if old_sha and old_sha == new_sha:
                vlog(f"[verbose] {remote_path}: SKIPPED (SHA match)")
                continue

            dest.write_bytes(content)
            repo.index.add([remote_path])
            actually_pushed.append(remote_path)
            vlog(f"[verbose] {remote_path}: STAGED for commit")

        if not actually_pushed:
            vlog("[verbose] No files differ — skipping commit and push")
            return []

        commit = repo.index.commit(commit_message)
        vlog(f"[verbose] Committed: {commit.hexsha} ({commit_message})")

        push_args = ["origin", branch]
        if force:
            push_args.insert(0, "--force")
        vlog(f"[verbose] Pushing: git push {' '.join(push_args)}")
        push_output = repo.git.push(*push_args)
        vlog(f"[verbose] Push output: {push_output or '(empty)'}")

        # Verify the push landed
        repo.git.fetch("origin", branch, depth=1)
        remote_head = repo.git.rev_parse(f"origin/{branch}")
        vlog(f"[verbose] Remote HEAD after push: {remote_head}")
        if remote_head == commit.hexsha:
            vlog("[verbose] Push confirmed — remote HEAD matches our commit")
        else:
            vlog(f"[verbose] WARNING: Remote HEAD ({remote_head}) != our commit ({commit.hexsha})")

        return actually_pushed
    except GitCommandError as exc:
        raise GitError(f"Failed to push to {url}: {exc}") from exc
    finally:
        shutil.rmtree(clone_dir, ignore_errors=True)


def fetch_single_file(url: str, branch: str, file_path: str) -> bytes | None:
    """Fetch a single file from a remote repo via sparse checkout.

    Returns the file contents, or ``None`` if the file does not exist.
    """
    clone_dir = _tmp_clone_dir()
    try:
        clone_dir, _repo = sparse_checkout_files(url, branch, [file_path])
        target = clone_dir / file_path
        if not target.exists():
            return None
        return target.read_bytes()
    except GitError:
        raise
    finally:
        shutil.rmtree(clone_dir, ignore_errors=True)


def cleanup(clone_dir: Path) -> None:
    """Remove a temporary clone directory."""
    shutil.rmtree(clone_dir, ignore_errors=True)
