"""Core get/push logic."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, List, Optional

import fnmatch
import re

import tlc_shared_docs.config as cfg
import tlc_shared_docs.git_ops as git_ops

logger = logging.getLogger(__name__)


def _glob_match(path: str, pattern: str) -> bool:
    """Match *path* against a glob *pattern* supporting ``**`` recursion.

    ``fnmatch`` doesn't handle ``**`` as recursive, so we convert the
    pattern to a regex where ``**/`` matches zero or more directory levels.
    """
    # Escape the pattern for regex, then restore glob semantics.
    # Handle **/ first (zero or more dirs), then lone ** , then single *
    regex = re.escape(pattern)
    # re.escape turns * into \*, ** into \*\*, / into /
    regex = regex.replace(r"\*\*/", "<<GLOBSTAR_SLASH>>")
    regex = regex.replace(r"\*\*", "<<GLOBSTAR>>")
    regex = regex.replace(r"\*", r"[^/]*")
    regex = regex.replace(r"\?", r"[^/]")
    regex = regex.replace("<<GLOBSTAR_SLASH>>", r"(.+/)?")
    regex = regex.replace("<<GLOBSTAR>>", r".*")
    return bool(re.fullmatch(regex, path))


def _resolve_config(
    root: Path,
    conf: cfg.SharedConfig,
    central_url: Optional[str] = None,
    _detect_identity: Callable[[Path], str] = cfg.detect_repo_identity,
    _fetch_file: Callable[..., bytes | None] = git_ops.fetch_single_file,
) -> tuple[cfg.SharedConfig, List[str]]:
    """If *conf* is in central mode, fetch the config from the source repo.

    Returns ``(resolved_config, messages)``.
    """
    messages: List[str] = []

    # CLI --central flag overrides the mode field in shared.json
    source_url = central_url or (conf.source_repo.url if conf.mode == "central" else None)
    if not source_url:
        return conf, messages

    # Detect this repo's org/repo identity from git remote
    org_repo = _detect_identity(root)
    config_path = cfg.central_config_path(org_repo)

    # Build source repo settings, allowing CLI override of URL
    source = cfg.SourceRepo(
        url=source_url,
        branch=conf.source_repo.branch if conf.source_repo.url == source_url else "main",
    )
    if central_url:
        source = cfg.SourceRepo(url=central_url, branch=conf.source_repo.branch)

    messages.append(f"Central mode: looking up {config_path} from {source.url}")

    # Fetch the central config file from the shared docs repo
    content = _fetch_file(source.url, source.branch, config_path)
    if content is None:
        raise FileNotFoundError(
            f"Central config not found: {config_path} in {source.url} ({source.branch})"
        )

    central_data = json.loads(content.decode("utf-8"))
    central_files = cfg.parse_shared_files(central_data)
    central_uploads = cfg.parse_upload_config(central_data)

    # Warn if local config also had shared_files -- central wins
    if conf.shared_files:
        messages.append(
            "WARNING: Local shared.json contains shared_files entries, "
            "but central mode is active. Central config takes precedence."
        )

    return cfg.SharedConfig(
        source_repo=source,
        shared_files=central_files,
        mode="central",
        uploads=central_uploads,
    ), messages


def _expand_get_entries(
    conf: cfg.SharedConfig,
    _list_remote: Callable[..., List[str]] = git_ops.list_remote_files,
) -> tuple[List[cfg.SharedFile], List[str]]:
    """Expand glob entries in the get list into concrete SharedFile objects.

    Returns ``(expanded_files, messages)``.  Messages contain
    warning info for glob resolution.
    """
    plain: List[cfg.SharedFile] = []
    glob_entries: List[cfg.SharedFile] = []
    messages: List[str] = []

    # Separate plain paths from glob patterns
    for sf in conf.shared_files:
        if sf.action != "get":
            continue
        if cfg.is_glob(sf.remote_path):
            glob_entries.append(sf)
        else:
            plain.append(sf)

    # Resolve each glob pattern against the remote tree
    for sf in glob_entries:
        matched = _list_remote(
            conf.source_repo.url,
            conf.source_repo.branch,
            sf.remote_path,
        )
        if not matched:
            messages.append(f"WARNING: No remote files matched pattern: {sf.remote_path}")
            continue

        # Strip the non-glob prefix to preserve relative directory structure
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
    _get_shas: Callable[..., dict[str, str]] = git_ops.get_remote_blob_shas,
    _sparse_checkout: Callable[..., tuple] = git_ops.sparse_checkout_files,
    _read_clone: Callable[..., bytes] = git_ops.read_file_from_clone,
    _cleanup: Callable[..., None] = git_ops.cleanup,
    _detect_identity: Callable[[Path], str] = cfg.detect_repo_identity,
    _fetch_file: Callable[..., bytes | None] = git_ops.fetch_single_file,
    _list_remote: Callable[..., List[str]] = git_ops.list_remote_files,
) -> List[str]:
    """Pull shared files from the remote repo.

    Returns a list of human-readable status messages.
    Dependency parameters (prefixed with _) allow test injection.
    """
    root = project_root or cfg.find_project_root()
    cfg.ensure_shared_dir(root)
    conf = cfg.load_config(root)

    # Resolve central mode if applicable
    conf, resolve_msgs = _resolve_config(
        root, conf, central_url,
        _detect_identity=_detect_identity,
        _fetch_file=_fetch_file,
    )
    messages: List[str] = list(resolve_msgs)

    # Expand any glob patterns into concrete file entries
    files_to_get, expand_msgs = _expand_get_entries(conf, _list_remote=_list_remote)
    messages.extend(expand_msgs)
    if not files_to_get:
        if not messages:
            messages.append("No files with action=get found in shared.json")
        return messages

    remote_paths = [f.remote_path for f in files_to_get]

    # Query remote blob SHAs to detect unchanged files (cheap, no blobs)
    stored_hashes = cfg.load_hashes(root)
    remote_shas = _get_shas(
        conf.source_repo.url,
        conf.source_repo.branch,
        remote_paths,
    )

    # Filter: only fetch files whose SHA changed or that don't exist locally
    files_needed: List[cfg.SharedFile] = []
    for sf in files_to_get:
        remote_sha = remote_shas.get(sf.remote_path)
        if remote_sha is None:
            # File doesn't exist on remote -- will produce a warning later
            files_needed.append(sf)
            continue
        stored_sha = stored_hashes.get(sf.remote_path)
        local = cfg.resolve_local_path(root, sf.local_path)
        if stored_sha == remote_sha and local.exists():
            messages.append(f"SKIP (unchanged): {sf.remote_path}")
        else:
            files_needed.append(sf)

    # Dry-run: show what would be fetched, then exit
    if dry_run:
        messages.extend(f"[dry-run] Would get: {sf.remote_path}" for sf in files_needed)
        return messages

    if not files_needed:
        messages.append("All files up to date.")
        return messages

    # Sparse-checkout only the files that actually changed
    needed_paths = [sf.remote_path for sf in files_needed]
    clone_dir, _repo = _sparse_checkout(
        conf.source_repo.url,
        conf.source_repo.branch,
        needed_paths,
    )

    try:
        for sf in files_needed:
            try:
                content = _read_clone(clone_dir, sf.remote_path)
            except FileNotFoundError:
                messages.append(f"WARNING: Remote file not found: {sf.remote_path}")
                continue

            # Write the fetched content to the local destination
            local = cfg.resolve_local_path(root, sf.local_path)
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(content)
            messages.append(f"OK: {sf.remote_path} -> {local.relative_to(root)}")

            # Track the blob SHA so we can skip this file next time
            sha = remote_shas.get(sf.remote_path)
            if sha:
                stored_hashes[sf.remote_path] = sha
    finally:
        _cleanup(clone_dir)

    # Persist updated hashes for future runs
    cfg.save_hashes(root, stored_hashes)

    return messages


def _discover_uploadable_files(
    project_root: Path,
    conf: cfg.SharedConfig,
) -> tuple[List[tuple[Path, str]], List[str]]:
    """Scan the shared directory for files not in ``shared_files``.

    Returns ``(candidates, messages)`` where each candidate is
    ``(local_path, remote_path)`` and messages contain DENIED warnings.

    Only files whose remote path matches an ``uploads.paths`` pattern
    are included; others produce a DENIED warning.
    """
    sdir = cfg.shared_dir_path(project_root)
    messages: List[str] = []

    # Internal files that are never uploaded
    internal = {".gitignore", "shared.json", ".shared-hashes.json"}

    # Collect all known local paths (from shared_files) so we skip them
    known_locals: set[Path] = set()
    for sf in conf.shared_files:
        known_locals.add(cfg.resolve_local_path(project_root, sf.local_path))

    upload_cfg = conf.uploads
    if not upload_cfg or not upload_cfg.allowed:
        return [], messages

    # Walk the shared directory for new files
    candidates: List[tuple[Path, str]] = []
    for local_file in sdir.rglob("*"):
        if not local_file.is_file():
            continue

        # Skip internal config/tracking files
        rel_to_shared = local_file.relative_to(sdir).as_posix()
        if rel_to_shared in internal:
            continue

        # Skip files already managed by shared_files entries
        if local_file in known_locals:
            continue

        # The remote path mirrors the relative path under shared dir
        remote_path = rel_to_shared

        # Check if any upload pattern permits this path
        permitted = any(
            _glob_match(remote_path, pat) for pat in upload_cfg.paths
        )
        if permitted:
            candidates.append((local_file, remote_path))
        else:
            messages.append(f"DENIED: {remote_path} does not match any upload pattern")

    return candidates, messages


def push_files(
    project_root: Optional[Path] = None,
    dry_run: bool = False,
    force: bool = False,
    central_url: Optional[str] = None,
    _sparse_checkout: Callable[..., tuple] = git_ops.sparse_checkout_files,
    _cleanup: Callable[..., None] = git_ops.cleanup,
    _push: Callable[..., None] = git_ops.push_files,
    _detect_identity: Callable[[Path], str] = cfg.detect_repo_identity,
    _fetch_file: Callable[..., bytes | None] = git_ops.fetch_single_file,
) -> List[str]:
    """Push local shared files to the remote repo.

    Returns a list of human-readable status messages.
    Dependency parameters (prefixed with _) allow test injection.
    """
    root = project_root or cfg.find_project_root()
    conf = cfg.load_config(root)

    # Resolve central mode if applicable
    conf, resolve_msgs = _resolve_config(
        root, conf, central_url,
        _detect_identity=_detect_identity,
        _fetch_file=_fetch_file,
    )
    messages: List[str] = list(resolve_msgs)

    files_to_push = [f for f in conf.shared_files if f.action == "push"]

    # Discover new files eligible for upload (central mode only)
    upload_candidates, upload_msgs = _discover_uploadable_files(root, conf)
    messages.extend(upload_msgs)

    if not files_to_push and not upload_candidates:
        messages.append("No files with action=push found in shared.json")
        return messages

    if dry_run:
        messages.extend(
            f"[dry-run] Would push: {f.local_path} -> {f.remote_path}"
            for f in files_to_push
        )
        # Show upload candidates in dry-run output
        messages.extend(
            f"[dry-run] Would upload: {remote_path}"
            for _, remote_path in upload_candidates
        )
        return messages

    # Build the file map: remote_path -> local file bytes
    file_map: dict[str, bytes] = {}

    for sf in files_to_push:
        local = cfg.resolve_local_path(root, sf.local_path)
        if not local.exists():
            messages.append(f"WARNING: Local file not found, skipping: {local}")
            continue
        file_map[sf.remote_path] = local.read_bytes()

    # Add upload candidates to the file map
    for local_file, remote_path in upload_candidates:
        file_map[remote_path] = local_file.read_bytes()

    if not file_map:
        messages.append("No files to push (all missing locally).")
        return messages

    # Conflict check: verify remote files haven't changed since last pull
    if not force:
        remote_paths = list(file_map.keys())
        clone_dir = None
        try:
            clone_dir, _repo = _sparse_checkout(
                conf.source_repo.url,
                conf.source_repo.branch,
                remote_paths,
            )
            for remote_path, local_content in file_map.items():
                remote_file = clone_dir / remote_path
                if remote_file.exists():
                    remote_content = remote_file.read_bytes()
                    if remote_content != local_content:
                        messages.append(
                            f"CONFLICT: {remote_path} differs on remote. "
                            f"Use --force to overwrite."
                        )
            if any("CONFLICT" in m for m in messages):
                messages.append("Push aborted due to conflicts. Use --force to overwrite.")
                return messages
        except git_ops.GitError as exc:
            # If we can't fetch to check conflicts, let the push attempt
            # handle the error -- log so it's not silently swallowed
            logger.warning("Could not check remote for conflicts: %s", exc)
        finally:
            if clone_dir:
                _cleanup(clone_dir)

    # Build the commit message from the local repo identity
    repo_name = _repo_name_from_root(root)
    branch_name = _current_branch(root)
    commit_msg = f"Updated by {repo_name} on {branch_name}"

    _push(
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
        from git import Repo
        repo = Repo(root)
        return str(repo.active_branch)
    except Exception as exc:
        logger.warning("Could not detect current branch: %s", exc)
        return "unknown"
