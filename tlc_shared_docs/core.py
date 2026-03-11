"""Core get/push logic."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Optional

from . import config as cfg
from . import git_ops


def get_files(
    project_root: Optional[Path] = None,
    dry_run: bool = False,
) -> List[str]:
    """Pull shared files from the remote repo.

    Returns a list of human-readable status messages.
    """
    root = project_root or cfg.find_project_root()
    cfg.ensure_shared_dir(root)
    conf = cfg.load_config(root)

    files_to_get = [f for f in conf.shared_files if f.action == "get"]
    if not files_to_get:
        return ["No files with action=get found in shared.json"]

    remote_paths = [f.remote_path for f in files_to_get]

    if dry_run:
        return [f"[dry-run] Would get: {rp}" for rp in remote_paths]

    # Sparse-checkout all needed files in one clone
    clone_dir, _repo = git_ops.sparse_checkout_files(
        url=conf.source_repo.url,
        branch=conf.source_repo.branch,
        file_paths=remote_paths,
    )

    messages: List[str] = []
    try:
        for sf in files_to_get:
            try:
                content = git_ops.read_file_from_clone(clone_dir, sf.remote_path)
            except FileNotFoundError:
                messages.append(f"WARNING: Remote file not found: {sf.remote_path}")
                continue

            local = cfg.resolve_local_path(root, sf.local_path)
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(content)
            messages.append(f"OK: {sf.remote_path} -> {local.relative_to(root)}")
    finally:
        git_ops.cleanup(clone_dir)

    return messages


def push_files(
    project_root: Optional[Path] = None,
    dry_run: bool = False,
    force: bool = False,
) -> List[str]:
    """Push local shared files to the remote repo.

    Returns a list of human-readable status messages.
    """
    root = project_root or cfg.find_project_root()
    conf = cfg.load_config(root)

    files_to_push = [f for f in conf.shared_files if f.action == "push"]
    if not files_to_push:
        return ["No files with action=push found in shared.json"]

    if dry_run:
        return [f"[dry-run] Would push: {f.local_path} -> {f.remote_path}" for f in files_to_push]

    # Build the file map: remote_path -> bytes
    file_map: dict[str, bytes] = {}
    messages: List[str] = []

    for sf in files_to_push:
        local = cfg.resolve_local_path(root, sf.local_path)
        if not local.exists():
            messages.append(f"WARNING: Local file not found, skipping: {local}")
            continue
        file_map[sf.remote_path] = local.read_bytes()

    if not file_map:
        messages.append("No files to push (all missing locally).")
        return messages

    # Conflict check: verify remote files haven't changed
    if not force:
        # Do a sparse checkout to compare
        remote_paths = list(file_map.keys())
        clone_dir = None
        try:
            clone_dir, _repo = git_ops.sparse_checkout_files(
                url=conf.source_repo.url,
                branch=conf.source_repo.branch,
                file_paths=remote_paths,
            )
            for remote_path, local_content in file_map.items():
                remote_file = clone_dir / remote_path
                if remote_file.exists():
                    remote_content = remote_file.read_bytes()
                    if remote_content != local_content:
                        # File differs — could be a remote change we'd overwrite.
                        # We can't know for sure without tracking last-pulled hashes,
                        # so we warn if the contents differ at all.
                        messages.append(
                            f"CONFLICT: {remote_path} differs on remote. "
                            f"Use --force to overwrite."
                        )
            if any("CONFLICT" in m for m in messages):
                messages.append("Push aborted due to conflicts. Use --force to overwrite.")
                return messages
        except git_ops.GitError:
            # If we can't even fetch to check, let the push attempt handle the error
            pass
        finally:
            if clone_dir:
                git_ops.cleanup(clone_dir)

    # Determine repo name and branch for commit message
    repo_name = _repo_name_from_root(root)
    branch_name = _current_branch(root)
    commit_msg = f"Updated by {repo_name} on {branch_name}"

    git_ops.push_files(
        url=conf.source_repo.url,
        branch=conf.source_repo.branch,
        file_map=file_map,
        commit_message=commit_msg,
        force=force,
    )

    for remote_path in file_map:
        messages.append(f"OK: pushed {remote_path}")

    return messages


def _repo_name_from_root(root: Path) -> str:
    """Best-effort repo name from the project root directory name."""
    return root.name


def _current_branch(root: Path) -> str:
    """Best-effort current branch name of the local repo."""
    try:
        from git import Repo, InvalidGitRepositoryError
        repo = Repo(root)
        return str(repo.active_branch)
    except Exception:
        return "unknown"
