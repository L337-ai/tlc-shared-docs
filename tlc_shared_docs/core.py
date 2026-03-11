"""Core get/push logic."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path, PurePosixPath
from typing import List, Optional

from . import config as cfg
from . import git_ops


def _resolve_config(
    root: Path,
    conf: cfg.SharedConfig,
    central_url: Optional[str] = None,
) -> tuple[cfg.SharedConfig, List[str]]:
    """If *conf* is in central mode, fetch the config from the source repo.

    Returns ``(resolved_config, messages)``.
    """
    messages: List[str] = []

    # CLI --central overrides mode
    source_url = central_url or (conf.source_repo.url if conf.mode == "central" else None)
    if not source_url:
        return conf, messages

    # Detect this repo's org/repo
    org_repo = cfg.detect_repo_identity(root)
    config_path = cfg.central_config_path(org_repo)

    # Use source_repo settings, but allow CLI override of URL
    source = cfg.SourceRepo(
        url=source_url,
        branch=conf.source_repo.branch if conf.source_repo.url == source_url else "main",
    )
    if central_url:
        source = cfg.SourceRepo(url=central_url, branch=conf.source_repo.branch)

    messages.append(f"Central mode: looking up {config_path} from {source.url}")

    content = git_ops.fetch_single_file(source.url, source.branch, config_path)
    if content is None:
        raise FileNotFoundError(
            f"Central config not found: {config_path} in {source.url} ({source.branch})"
        )

    central_data = json.loads(content.decode("utf-8"))
    central_files = cfg.parse_shared_files(central_data)

    # Warn if local config also had shared_files
    if conf.shared_files:
        messages.append(
            "WARNING: Local shared.json contains shared_files entries, "
            "but central mode is active. Central config takes precedence."
        )

    return cfg.SharedConfig(
        source_repo=source,
        shared_files=central_files,
        mode="central",
    ), messages


def _expand_get_entries(
    conf: cfg.SharedConfig,
) -> tuple[List[cfg.SharedFile], List[str]]:
    """Expand glob entries in the get list into concrete SharedFile objects.

    Returns ``(expanded_files, messages)``.  Messages contain dry-run or
    warning info for glob resolution.
    """
    plain: List[cfg.SharedFile] = []
    glob_entries: List[cfg.SharedFile] = []
    messages: List[str] = []

    for sf in conf.shared_files:
        if sf.action != "get":
            continue
        if cfg.is_glob(sf.remote_path):
            glob_entries.append(sf)
        else:
            plain.append(sf)

    for sf in glob_entries:
        matched = git_ops.list_remote_files(
            url=conf.source_repo.url,
            branch=conf.source_repo.branch,
            pattern=sf.remote_path,
        )
        if not matched:
            messages.append(f"WARNING: No remote files matched pattern: {sf.remote_path}")
            continue

        # Determine the prefix to strip so we preserve relative structure
        prefix = cfg.glob_prefix(sf.remote_path)

        for remote_path in matched:
            # Build a local path that preserves directory structure under local_path
            if prefix:
                relative = remote_path[len(prefix):].lstrip("/")
            else:
                relative = remote_path
            local_path = sf.local_path.rstrip("/") + "/" + relative

            plain.append(cfg.SharedFile(
                remote_path=remote_path,
                local_path=local_path,
                action="get",
            ))

        messages.append(
            f"Glob '{sf.remote_path}' matched {len(matched)} file(s)"
        )

    return plain, messages


def get_files(
    project_root: Optional[Path] = None,
    dry_run: bool = False,
    central_url: Optional[str] = None,
) -> List[str]:
    """Pull shared files from the remote repo.

    Returns a list of human-readable status messages.
    """
    root = project_root or cfg.find_project_root()
    cfg.ensure_shared_dir(root)
    conf = cfg.load_config(root)
    conf, resolve_msgs = _resolve_config(root, conf, central_url)
    messages: List[str] = list(resolve_msgs)

    files_to_get, expand_msgs = _expand_get_entries(conf)
    messages.extend(expand_msgs)
    if not files_to_get:
        if not messages:
            messages.append("No files with action=get found in shared.json")
        return messages

    remote_paths = [f.remote_path for f in files_to_get]

    # Query remote blob SHAs to detect unchanged files
    stored_hashes = cfg.load_hashes(root)
    remote_shas = git_ops.get_remote_blob_shas(
        url=conf.source_repo.url,
        branch=conf.source_repo.branch,
        file_paths=remote_paths,
    )

    # Filter: only fetch files whose SHA changed or that don't exist locally
    files_needed: List[cfg.SharedFile] = []
    for sf in files_to_get:
        remote_sha = remote_shas.get(sf.remote_path)
        if remote_sha is None:
            # File doesn't exist on remote — will produce a warning later
            files_needed.append(sf)
            continue
        stored_sha = stored_hashes.get(sf.remote_path)
        local = cfg.resolve_local_path(root, sf.local_path)
        if stored_sha == remote_sha and local.exists():
            messages.append(f"SKIP (unchanged): {sf.remote_path}")
        else:
            files_needed.append(sf)

    if dry_run:
        messages.extend(f"[dry-run] Would get: {sf.remote_path}" for sf in files_needed)
        return messages

    if not files_needed:
        messages.append("All files up to date.")
        return messages

    # Sparse-checkout only the files that changed
    needed_paths = [sf.remote_path for sf in files_needed]
    clone_dir, _repo = git_ops.sparse_checkout_files(
        url=conf.source_repo.url,
        branch=conf.source_repo.branch,
        file_paths=needed_paths,
    )

    try:
        for sf in files_needed:
            try:
                content = git_ops.read_file_from_clone(clone_dir, sf.remote_path)
            except FileNotFoundError:
                messages.append(f"WARNING: Remote file not found: {sf.remote_path}")
                continue

            local = cfg.resolve_local_path(root, sf.local_path)
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(content)
            messages.append(f"OK: {sf.remote_path} -> {local.relative_to(root)}")

            # Update stored hash
            sha = remote_shas.get(sf.remote_path)
            if sha:
                stored_hashes[sf.remote_path] = sha
    finally:
        git_ops.cleanup(clone_dir)

    # Persist updated hashes
    cfg.save_hashes(root, stored_hashes)

    return messages


def push_files(
    project_root: Optional[Path] = None,
    dry_run: bool = False,
    force: bool = False,
    central_url: Optional[str] = None,
) -> List[str]:
    """Push local shared files to the remote repo.

    Returns a list of human-readable status messages.
    """
    root = project_root or cfg.find_project_root()
    conf = cfg.load_config(root)
    conf, resolve_msgs = _resolve_config(root, conf, central_url)
    messages: List[str] = list(resolve_msgs)

    files_to_push = [f for f in conf.shared_files if f.action == "push"]
    if not files_to_push:
        messages.append("No files with action=push found in shared.json")
        return messages

    if dry_run:
        messages.extend(f"[dry-run] Would push: {f.local_path} -> {f.remote_path}" for f in files_to_push)
        return messages

    # Build the file map: remote_path -> bytes
    file_map: dict[str, bytes] = {}

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
