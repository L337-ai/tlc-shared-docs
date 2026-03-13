"""Tests for the core get/push logic."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest

from tlc_shared_docs.config import SharedConfig, SharedFile, SourceRepo, UploadConfig, save_hashes, load_hashes
from tlc_shared_docs.core import _discover_uploadable_files, _resolve_config, get_files, push_files


# ---------------------------------------------------------------------------
# Explicit stubs -- no unittest.mock allowed (see AGENTS.md)
# ---------------------------------------------------------------------------

class StubGitOps:
    """Configurable stub for git_ops functions, injected via _ parameters."""

    def __init__(
        self,
        remote_shas: dict[str, str] | None = None,
        sparse_files: dict[str, bytes] | None = None,
        list_remote_result: List[str] | None = None,
        fetch_file_result: bytes | None = None,
    ):
        # Configurable return values
        self.remote_shas = remote_shas or {}
        self.sparse_files = sparse_files or {}
        self.list_remote_result = list_remote_result or []
        self.fetch_file_result = fetch_file_result

        # Call tracking
        self.sparse_checkout_called = False
        self.sparse_checkout_paths: List[str] = []
        self.push_called = False
        self.push_kwargs: dict = {}
        self.cleanup_called = False

    def get_remote_blob_shas(self, url: str, branch: str, file_paths: List[str]) -> dict[str, str]:
        return self.remote_shas

    def sparse_checkout_files(self, url: str, branch: str, file_paths: List[str]) -> tuple[Path, object]:
        self.sparse_checkout_called = True
        self.sparse_checkout_paths = file_paths

        # Create a temporary directory with the stubbed files
        import tempfile
        clone_dir = Path(tempfile.mkdtemp(prefix="stub_clone_"))
        for path, content in self.sparse_files.items():
            dest = clone_dir / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        return clone_dir, None

    def read_file_from_clone(self, clone_dir: Path, remote_path: str) -> bytes:
        target = clone_dir / remote_path
        if not target.exists():
            raise FileNotFoundError(f"File not found in clone: {remote_path}")
        return target.read_bytes()

    def cleanup(self, clone_dir: Path) -> None:
        self.cleanup_called = True
        import shutil
        shutil.rmtree(clone_dir, ignore_errors=True)

    def list_remote_files(self, url: str, branch: str, pattern: str) -> List[str]:
        return self.list_remote_result

    def fetch_single_file(self, url: str, branch: str, file_path: str) -> bytes | None:
        return self.fetch_file_result

    def push_files(self, url: str, branch: str, file_map: dict, commit_message: str, force: bool = False) -> None:
        self.push_called = True
        self.push_kwargs = {
            "url": url, "branch": branch, "file_map": file_map,
            "commit_message": commit_message, "force": force,
        }


def _stub_detect_identity(root: Path) -> str:
    """Stub identity detector that always returns a fixed org/repo."""
    return "myorg/myapp"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_config(shared_dir: Path, config: dict) -> None:
    """Write a shared.json config dict to the test shared directory."""
    (shared_dir / "shared.json").write_text(json.dumps(config), encoding="utf-8")


def _make_config(
    url: str = "https://example.com/repo.git",
    branch: str = "main",
    shared_files: list | None = None,
    mode: str = "local",
) -> dict:
    """Build a shared.json config dict."""
    config: dict = {"source_repo": {"url": url, "branch": branch}}
    if mode != "local":
        config["mode"] = mode
    if shared_files is not None:
        config["shared_files"] = shared_files
    return config


# ===========================================================================
# GET tests
# ===========================================================================


class TestGetDryRunShowsPlannedFiles:
    def test_dry_run_lists_files_to_fetch(self, configured_project):
        root, _ = configured_project
        stub = StubGitOps(remote_shas={"Python.gitignore": "abc123"})
        messages = get_files(
            project_root=root, dry_run=True,
            _get_shas=stub.get_remote_blob_shas,
        )
        assert any("[dry-run]" in m and "Python.gitignore" in m for m in messages)

    def test_no_get_files_produces_message(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(
            shared_files=[{"remote_path": "a.md", "local_path": "a.md", "action": "push"}]
        ))
        messages = get_files(project_root=root)
        assert any("No files with action=get" in m for m in messages)


class TestGetGlobExpandsToConcreteFiles:
    def test_glob_resolves_and_fetches_matched_files(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(
            shared_files=[{"remote_path": "stories/**/*", "local_path": "stories", "action": "get"}]
        ))

        stub = StubGitOps(
            list_remote_result=["stories/chapter1/intro.md", "stories/chapter2/outro.md"],
            remote_shas={
                "stories/chapter1/intro.md": "sha1",
                "stories/chapter2/outro.md": "sha2",
            },
            sparse_files={
                "stories/chapter1/intro.md": b"# Intro",
                "stories/chapter2/outro.md": b"# Outro",
            },
        )
        messages = get_files(
            project_root=root,
            _get_shas=stub.get_remote_blob_shas,
            _sparse_checkout=stub.sparse_checkout_files,
            _read_clone=stub.read_file_from_clone,
            _cleanup=stub.cleanup,
            _list_remote=stub.list_remote_files,
        )
        assert any("matched 2 file(s)" in m for m in messages)
        assert stub.sparse_checkout_called

    def test_glob_dry_run_shows_resolved_files(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(
            shared_files=[{"remote_path": "Global/*.gitignore", "local_path": "global_ignores", "action": "get"}]
        ))

        stub = StubGitOps(
            list_remote_result=["Global/Vim.gitignore", "Global/macOS.gitignore"],
            remote_shas={"Global/Vim.gitignore": "sha1", "Global/macOS.gitignore": "sha2"},
        )
        messages = get_files(
            project_root=root, dry_run=True,
            _get_shas=stub.get_remote_blob_shas,
            _list_remote=stub.list_remote_files,
        )
        assert any("[dry-run]" in m for m in messages)
        assert any("Vim.gitignore" in m for m in messages)

    def test_glob_with_no_matches_warns(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(
            shared_files=[{"remote_path": "nonexistent/**/*", "local_path": "nope", "action": "get"}]
        ))

        stub = StubGitOps(list_remote_result=[])
        messages = get_files(
            project_root=root,
            _list_remote=stub.list_remote_files,
        )
        assert any("WARNING" in m and "No remote files matched" in m for m in messages)

    def test_glob_preserves_directory_structure_under_local_path(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(
            shared_files=[{"remote_path": "stories/**/*", "local_path": "mystories", "action": "get"}]
        ))

        stub = StubGitOps(
            list_remote_result=["stories/a/b.md"],
            remote_shas={"stories/a/b.md": "sha1"},
            sparse_files={"stories/a/b.md": b"hello"},
        )
        messages = get_files(
            project_root=root,
            _get_shas=stub.get_remote_blob_shas,
            _sparse_checkout=stub.sparse_checkout_files,
            _read_clone=stub.read_file_from_clone,
            _cleanup=stub.cleanup,
            _list_remote=stub.list_remote_files,
        )
        # File should land at shared_dir / mystories / a / b.md
        expected = shared_dir / "mystories" / "a" / "b.md"
        assert expected.exists()
        assert expected.read_bytes() == b"hello"


class TestGetGlobIntegration:
    @pytest.mark.integration
    def test_glob_fetches_real_files_from_github(self, fake_project):
        """Fetch Global/*.gitignore from github/gitignore."""
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(
            url="https://github.com/github/gitignore.git",
            shared_files=[{"remote_path": "Global/*.gitignore", "local_path": "global_ignores", "action": "get"}]
        ))

        messages = get_files(project_root=root)
        assert any("matched" in m for m in messages)
        assert any("OK" in m for m in messages)

        # Should have fetched multiple files into global_ignores/
        dest = shared_dir / "global_ignores"
        assert dest.is_dir()
        fetched = list(dest.glob("*.gitignore"))
        assert len(fetched) > 5


class TestGetFilesIntegration:
    @pytest.mark.integration
    def test_get_fetches_real_file_from_github(self, configured_project):
        root, shared_dir = configured_project
        messages = get_files(project_root=root)
        assert any("OK" in m for m in messages)

        fetched = shared_dir / "python_gitignore.txt"
        assert fetched.exists()
        content = fetched.read_text(encoding="utf-8")
        assert "__pycache__" in content


# ===========================================================================
# SHA-based skip logic
# ===========================================================================


class TestSkipUnchangedFiles:
    def test_skips_file_when_sha_matches_and_local_exists(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(
            shared_files=[{"remote_path": "doc.md", "local_path": "doc.md", "action": "get"}]
        ))

        # Write existing local file and matching hash
        (shared_dir / "doc.md").write_text("existing content")
        save_hashes(root, {"doc.md": "abc123"})

        # Remote SHA matches stored hash -- should skip
        stub = StubGitOps(remote_shas={"doc.md": "abc123"})
        messages = get_files(
            project_root=root,
            _get_shas=stub.get_remote_blob_shas,
            _sparse_checkout=stub.sparse_checkout_files,
            _read_clone=stub.read_file_from_clone,
            _cleanup=stub.cleanup,
        )
        assert any("SKIP (unchanged)" in m for m in messages)
        assert not stub.sparse_checkout_called

    def test_fetches_when_remote_sha_differs_from_stored(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(
            shared_files=[{"remote_path": "doc.md", "local_path": "doc.md", "action": "get"}]
        ))
        save_hashes(root, {"doc.md": "old_sha"})

        stub = StubGitOps(
            remote_shas={"doc.md": "new_sha"},
            sparse_files={"doc.md": b"new content"},
        )
        messages = get_files(
            project_root=root,
            _get_shas=stub.get_remote_blob_shas,
            _sparse_checkout=stub.sparse_checkout_files,
            _read_clone=stub.read_file_from_clone,
            _cleanup=stub.cleanup,
        )
        assert any("OK" in m for m in messages)
        assert stub.sparse_checkout_called

    def test_fetches_when_local_file_missing_despite_matching_sha(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(
            shared_files=[{"remote_path": "doc.md", "local_path": "doc.md", "action": "get"}]
        ))
        # SHA matches but local file does not exist
        save_hashes(root, {"doc.md": "abc123"})

        stub = StubGitOps(
            remote_shas={"doc.md": "abc123"},
            sparse_files={"doc.md": b"content"},
        )
        messages = get_files(
            project_root=root,
            _get_shas=stub.get_remote_blob_shas,
            _sparse_checkout=stub.sparse_checkout_files,
            _read_clone=stub.read_file_from_clone,
            _cleanup=stub.cleanup,
        )
        assert any("OK" in m for m in messages)
        assert stub.sparse_checkout_called

    def test_persists_hashes_after_successful_fetch(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(
            shared_files=[{"remote_path": "doc.md", "local_path": "doc.md", "action": "get"}]
        ))

        stub = StubGitOps(
            remote_shas={"doc.md": "new_sha"},
            sparse_files={"doc.md": b"content"},
        )
        get_files(
            project_root=root,
            _get_shas=stub.get_remote_blob_shas,
            _sparse_checkout=stub.sparse_checkout_files,
            _read_clone=stub.read_file_from_clone,
            _cleanup=stub.cleanup,
        )
        hashes = load_hashes(root)
        assert hashes["doc.md"] == "new_sha"

    def test_dry_run_shows_skip_and_would_get(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(
            shared_files=[
                {"remote_path": "a.md", "local_path": "a.md", "action": "get"},
                {"remote_path": "b.md", "local_path": "b.md", "action": "get"},
            ]
        ))
        # a.md is unchanged, b.md is new
        (shared_dir / "a.md").write_text("old")
        save_hashes(root, {"a.md": "sha_a"})

        stub = StubGitOps(remote_shas={"a.md": "sha_a", "b.md": "sha_b"})
        messages = get_files(
            project_root=root, dry_run=True,
            _get_shas=stub.get_remote_blob_shas,
        )
        assert any("SKIP (unchanged)" in m and "a.md" in m for m in messages)
        assert any("[dry-run]" in m and "b.md" in m for m in messages)


# ===========================================================================
# PUSH tests
# ===========================================================================


class TestCleanRemovesStaleFiles:
    """Tests for --clean flag removing files no longer in the share list."""

    def test_clean_removes_file_not_in_shared_files(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(
            shared_files=[{"remote_path": "keep.md", "local_path": "keep.md", "action": "get"}]
        ))
        # Both files exist locally, but only keep.md is in shared_files
        (shared_dir / "keep.md").write_text("kept")
        (shared_dir / "stale.md").write_text("should be removed")

        stub = StubGitOps(
            remote_shas={"keep.md": "sha1"},
            sparse_files={"keep.md": b"kept"},
        )
        messages = get_files(
            project_root=root, clean=True,
            _get_shas=stub.get_remote_blob_shas,
            _sparse_checkout=stub.sparse_checkout_files,
            _read_clone=stub.read_file_from_clone,
            _cleanup=stub.cleanup,
        )
        assert not (shared_dir / "stale.md").exists()
        assert (shared_dir / "keep.md").exists()
        assert any("REMOVED" in m and "stale.md" in m for m in messages)

    def test_clean_preserves_internal_files(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(shared_files=[]))
        (shared_dir / ".gitignore").write_text("*")
        (shared_dir / ".shared-hashes.json").write_text("{}")

        stub = StubGitOps()
        get_files(project_root=root, clean=True)

        assert (shared_dir / ".gitignore").exists()
        assert (shared_dir / "shared.json").exists()
        assert (shared_dir / ".shared-hashes.json").exists()

    def test_clean_dry_run_shows_would_remove(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(shared_files=[]))
        (shared_dir / "orphan.md").write_text("orphaned file")

        messages = get_files(project_root=root, dry_run=True, clean=True)
        assert (shared_dir / "orphan.md").exists()  # not deleted in dry-run
        assert any("[dry-run] Would remove:" in m and "orphan.md" in m for m in messages)

    def test_clean_scopes_to_project_subdirectory(self, fake_project):
        root, shared_dir = fake_project
        config = {
            "projects": {
                "alpha": {
                    "source_repo": {"url": "https://example.com/alpha.git"},
                    "shared_files": [
                        {"remote_path": "doc.md", "local_path": "doc.md", "action": "get"}
                    ],
                },
            },
        }
        _write_config(shared_dir, config)

        # Create files in alpha/ and a sibling directory
        (shared_dir / "alpha").mkdir()
        (shared_dir / "alpha" / "doc.md").write_text("kept")
        (shared_dir / "alpha" / "stale.md").write_text("should go")
        (shared_dir / "other").mkdir()
        (shared_dir / "other" / "safe.md").write_text("not touched")

        stub = StubGitOps(
            remote_shas={"doc.md": "sha1"},
            sparse_files={"doc.md": b"kept"},
        )
        messages = get_files(
            project_root=root, project="alpha", clean=True,
            _get_shas=stub.get_remote_blob_shas,
            _sparse_checkout=stub.sparse_checkout_files,
            _read_clone=stub.read_file_from_clone,
            _cleanup=stub.cleanup,
        )
        assert not (shared_dir / "alpha" / "stale.md").exists()
        assert (shared_dir / "alpha" / "doc.md").exists()
        assert (shared_dir / "other" / "safe.md").exists()  # untouched

    def test_no_clean_leaves_stale_files(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(
            shared_files=[{"remote_path": "keep.md", "local_path": "keep.md", "action": "get"}]
        ))
        (shared_dir / "keep.md").write_text("kept")
        (shared_dir / "stale.md").write_text("should stay without --clean")

        stub = StubGitOps(
            remote_shas={"keep.md": "sha1"},
            sparse_files={"keep.md": b"kept"},
        )
        get_files(
            project_root=root,
            _get_shas=stub.get_remote_blob_shas,
            _sparse_checkout=stub.sparse_checkout_files,
            _read_clone=stub.read_file_from_clone,
            _cleanup=stub.cleanup,
        )
        assert (shared_dir / "stale.md").exists()

    def test_summary_includes_removed_count(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(shared_files=[]))
        (shared_dir / "old1.md").write_text("x")
        (shared_dir / "old2.md").write_text("y")

        messages = get_files(project_root=root, clean=True)
        assert any("2 removed" in m for m in messages)


class TestPushDryRunShowsPlannedFiles:
    def test_dry_run_lists_files_to_push(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(
            shared_files=[{"remote_path": "docs/guide.md", "local_path": "guide.md", "action": "push"}]
        ))
        messages = push_files(project_root=root, dry_run=True)
        assert len(messages) == 1
        assert "[dry-run]" in messages[0]
        assert "guide.md" in messages[0]


class TestPushBehavior:
    def test_warns_when_local_file_missing(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(
            shared_files=[{"remote_path": "docs/guide.md", "local_path": "guide.md", "action": "push"}]
        ))
        messages = push_files(project_root=root)
        assert any("WARNING" in m for m in messages)
        assert any("missing" in m.lower() for m in messages)

    def test_calls_push_with_force_flag(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(
            shared_files=[{"remote_path": "docs/guide.md", "local_path": "guide.md", "action": "push"}]
        ))
        (shared_dir / "guide.md").write_text("# Guide\nHello", encoding="utf-8")

        stub = StubGitOps()
        messages = push_files(
            project_root=root, force=True,
            _sparse_checkout=stub.sparse_checkout_files,
            _cleanup=stub.cleanup,
            _push=stub.push_files,
        )
        assert stub.push_called
        assert any("OK" in m for m in messages)

    def test_no_push_files_produces_message(self, configured_project):
        root, _ = configured_project
        # Default sample config only has action=get files
        messages = push_files(project_root=root)
        assert "No files with action=push" in messages[0]


# ===========================================================================
# CLI tests
# ===========================================================================


class TestCLI:
    def test_get_dry_run_via_entry_point(self, configured_project):
        """CLI get --dry-run should not raise."""
        from tlc_shared_docs.cli import main

        root, _ = configured_project

        # Stub the SHA lookup so we don't hit the network
        stub = StubGitOps(remote_shas={"Python.gitignore": "abc123"})

        # We need to temporarily override the default in get_files.
        # Since CLI calls get_files without injection, we swap the module-level
        # function reference temporarily.
        import tlc_shared_docs.git_ops as real_git_ops
        original = real_git_ops.get_remote_blob_shas
        real_git_ops.get_remote_blob_shas = stub.get_remote_blob_shas
        try:
            import tlc_shared_docs.config as cfg_mod
            original_find = cfg_mod.find_project_root
            cfg_mod.find_project_root = lambda start=None: root
            try:
                main(["get", "--dry-run"])
            finally:
                cfg_mod.find_project_root = original_find
        finally:
            real_git_ops.get_remote_blob_shas = original

    def test_no_command_exits_with_error(self):
        from tlc_shared_docs.cli import main
        with pytest.raises(SystemExit):
            main([])

    def test_list_shows_projects(self, fake_project, capsys):
        from tlc_shared_docs.cli import main

        root, shared_dir = fake_project
        config = {
            "projects": {
                "auth": {"source_repo": {"url": "https://example.com/auth.git"}, "mode": "central"},
                "agent": {"source_repo": {"url": "https://example.com/agent.git"}},
            },
            "default_project": "agent",
        }
        _write_config(shared_dir, config)

        import tlc_shared_docs.config as cfg_mod
        original_find = cfg_mod.find_project_root
        cfg_mod.find_project_root = lambda start=None: root
        try:
            main(["list"])
        finally:
            cfg_mod.find_project_root = original_find

        output = capsys.readouterr().out
        assert "agent (default)" in output
        assert "auth" in output
        assert "example.com/auth.git" in output

    def test_list_legacy_config(self, configured_project, capsys):
        from tlc_shared_docs.cli import main

        root, _ = configured_project
        import tlc_shared_docs.config as cfg_mod
        original_find = cfg_mod.find_project_root
        cfg_mod.find_project_root = lambda start=None: root
        try:
            main(["list"])
        finally:
            cfg_mod.find_project_root = original_find

        output = capsys.readouterr().out
        assert "Single-source config" in output

    def test_version_flag_exits_cleanly(self):
        from tlc_shared_docs.cli import main
        with pytest.raises(SystemExit) as exc_info:
            main(["--version"])
        assert exc_info.value.code == 0


# ===========================================================================
# Central mode tests
# ===========================================================================


class TestResolveCentralConfig:
    """Tests for central mode config resolution."""

    def _make_conf(self, mode="central", url="https://example.com/shared.git", shared_files=None):
        return SharedConfig(
            source_repo=SourceRepo(url=url, branch="main"),
            shared_files=shared_files or [],
            mode=mode,
        )

    def test_central_fetches_config_from_source_repo(self, tmp_path):
        central_data = {
            "shared_files": [
                {"remote_path": "docs/intro.md", "local_path": "intro.md", "action": "get"}
            ]
        }

        # Track what fetch_file was called with
        fetch_calls = []

        def fake_fetch(url, branch, path):
            fetch_calls.append((url, branch, path))
            return json.dumps(central_data).encode()

        conf = self._make_conf()
        resolved, msgs = _resolve_config(
            tmp_path, conf,
            _detect_identity=_stub_detect_identity,
            _fetch_file=fake_fetch,
        )

        assert fetch_calls == [("https://example.com/shared.git", "main", ".configs/myorg/myapp.json")]
        assert resolved.mode == "central"
        assert len(resolved.shared_files) == 1
        assert resolved.shared_files[0].remote_path == "docs/intro.md"
        assert any("Central mode" in m for m in msgs)

    def test_warns_when_local_shared_files_overridden_by_central(self, tmp_path):
        central_data = {
            "shared_files": [
                {"remote_path": "a.md", "local_path": "a.md", "action": "get"}
            ]
        }

        conf = self._make_conf(shared_files=[
            SharedFile(remote_path="local.md", local_path="local.md", action="get")
        ])
        resolved, msgs = _resolve_config(
            tmp_path, conf,
            _detect_identity=_stub_detect_identity,
            _fetch_file=lambda u, b, p: json.dumps(central_data).encode(),
        )

        assert any("WARNING" in m and "Central config takes precedence" in m for m in msgs)
        # Central files win
        assert len(resolved.shared_files) == 1
        assert resolved.shared_files[0].remote_path == "a.md"

    def test_raises_when_central_config_not_found(self, tmp_path):
        conf = self._make_conf()
        with pytest.raises(FileNotFoundError, match="Central config not found"):
            _resolve_config(
                tmp_path, conf,
                _detect_identity=_stub_detect_identity,
                _fetch_file=lambda u, b, p: None,
            )

    def test_local_mode_skips_central_resolution(self, tmp_path):
        conf = self._make_conf(mode="local")
        resolved, msgs = _resolve_config(tmp_path, conf)
        assert resolved is conf
        assert msgs == []

    def test_cli_central_url_overrides_local_mode(self, tmp_path):
        central_data = {
            "shared_files": [
                {"remote_path": "x.md", "local_path": "x.md", "action": "get"}
            ]
        }

        fetch_calls = []

        def fake_fetch(url, branch, path):
            fetch_calls.append((url, branch, path))
            return json.dumps(central_data).encode()

        conf = self._make_conf(mode="local")
        resolved, msgs = _resolve_config(
            tmp_path, conf,
            central_url="https://override.com/docs.git",
            _detect_identity=_stub_detect_identity,
            _fetch_file=fake_fetch,
        )

        assert fetch_calls[0][0] == "https://override.com/docs.git"
        assert resolved.mode == "central"

    def test_central_get_dry_run_shows_resolved_files(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(mode="central"))

        central_data = {
            "shared_files": [
                {"remote_path": "guide.md", "local_path": "guide.md", "action": "get"}
            ]
        }

        stub = StubGitOps(
            fetch_file_result=json.dumps(central_data).encode(),
            remote_shas={"guide.md": "sha1"},
        )
        messages = get_files(
            project_root=root, dry_run=True,
            _get_shas=stub.get_remote_blob_shas,
            _detect_identity=_stub_detect_identity,
            _fetch_file=stub.fetch_single_file,
        )
        assert any("[dry-run]" in m for m in messages)
        assert any("guide.md" in m for m in messages)

    def test_central_push_dry_run_shows_resolved_files(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, _make_config(mode="central"))

        central_data = {
            "shared_files": [
                {"remote_path": "guide.md", "local_path": "guide.md", "action": "push"}
            ]
        }

        stub = StubGitOps(fetch_file_result=json.dumps(central_data).encode())
        messages = push_files(
            project_root=root, dry_run=True,
            _detect_identity=_stub_detect_identity,
            _fetch_file=stub.fetch_single_file,
        )
        assert any("[dry-run]" in m for m in messages)
        assert any("guide.md" in m for m in messages)


# ===========================================================================
# Upload discovery tests
# ===========================================================================


class TestDiscoverUploadableFiles:
    """Tests for auto-detection of new local files to upload."""

    def _conf_with_uploads(self, paths, shared_files=None):
        """Build a SharedConfig with upload permissions."""
        return SharedConfig(
            source_repo=SourceRepo(url="https://example.com/shared.git", branch="main"),
            shared_files=shared_files or [],
            mode="central",
            uploads=UploadConfig(allowed=True, paths=paths),
        )

    def test_globstar_matches_zero_intermediate_segments(self, fake_project):
        """stories/**/*.md must match stories/base.md (zero dirs) and stories/sub/deep.md."""
        root, shared_dir = fake_project
        stories = shared_dir / "stories"
        stories.mkdir()
        (stories / "base.md").write_text("root-level file")
        sub = stories / "bugs"
        sub.mkdir()
        (sub / "BUG-10.md").write_text("nested file")

        conf = self._conf_with_uploads(["stories/**/*.md"])
        candidates, msgs = _discover_uploadable_files(root, conf)

        remote_paths = {c[1] for c in candidates}
        assert "stories/base.md" in remote_paths
        assert "stories/bugs/BUG-10.md" in remote_paths
        assert not msgs

    def test_discovers_new_file_matching_upload_pattern(self, fake_project):
        root, shared_dir = fake_project
        # Create a new file in the shared dir that's not in shared_files
        contrib_dir = shared_dir / "contributions"
        contrib_dir.mkdir()
        (contrib_dir / "new-guide.md").write_text("# New Guide")

        conf = self._conf_with_uploads(["contributions/**/*.md"])
        candidates, msgs = _discover_uploadable_files(root, conf)

        assert len(candidates) == 1
        assert candidates[0][1] == "contributions/new-guide.md"
        assert not msgs  # no denials

    def test_denies_file_not_matching_any_pattern(self, fake_project):
        root, shared_dir = fake_project
        (shared_dir / "rogue.txt").write_text("not permitted")

        conf = self._conf_with_uploads(["contributions/**/*.md"])
        candidates, msgs = _discover_uploadable_files(root, conf)

        assert len(candidates) == 0
        assert any("DENIED" in m and "rogue.txt" in m for m in msgs)

    def test_skips_internal_files(self, fake_project):
        root, shared_dir = fake_project
        # Internal files should never be candidates
        (shared_dir / ".gitignore").write_text("*")
        (shared_dir / "shared.json").write_text("{}")
        (shared_dir / ".shared-hashes.json").write_text("{}")

        conf = self._conf_with_uploads(["*"])
        candidates, msgs = _discover_uploadable_files(root, conf)
        assert len(candidates) == 0

    def test_skips_files_already_in_shared_files(self, fake_project):
        root, shared_dir = fake_project
        (shared_dir / "existing.md").write_text("already managed")

        managed = [SharedFile(remote_path="docs/existing.md", local_path="existing.md", action="push")]
        conf = self._conf_with_uploads(["*.md"], shared_files=managed)
        candidates, msgs = _discover_uploadable_files(root, conf)

        assert len(candidates) == 0

    def test_returns_empty_when_uploads_not_allowed(self, fake_project):
        root, shared_dir = fake_project
        (shared_dir / "new.md").write_text("content")

        conf = SharedConfig(
            source_repo=SourceRepo(url="https://example.com/shared.git", branch="main"),
            shared_files=[],
            mode="central",
            uploads=UploadConfig(allowed=False, paths=["*.md"]),
        )
        candidates, msgs = _discover_uploadable_files(root, conf)
        assert len(candidates) == 0

    def test_returns_empty_when_no_upload_config(self, fake_project):
        root, shared_dir = fake_project
        (shared_dir / "new.md").write_text("content")

        conf = SharedConfig(
            source_repo=SourceRepo(url="https://example.com/shared.git", branch="main"),
            shared_files=[],
            mode="central",
            uploads=None,
        )
        candidates, msgs = _discover_uploadable_files(root, conf)
        assert len(candidates) == 0

    def test_multiple_patterns_permit_different_files(self, fake_project):
        root, shared_dir = fake_project
        (shared_dir / "guide.md").write_text("guide")
        img_dir = shared_dir / "images"
        img_dir.mkdir()
        (img_dir / "diagram.png").write_bytes(b"\x89PNG")

        conf = self._conf_with_uploads(["*.md", "images/*.png"])
        candidates, msgs = _discover_uploadable_files(root, conf)

        remote_paths = {c[1] for c in candidates}
        assert "guide.md" in remote_paths
        assert "images/diagram.png" in remote_paths


class TestPushWithUploadDiscovery:
    """Tests for upload integration in push_files."""

    def test_dry_run_shows_upload_candidates(self, fake_project):
        root, shared_dir = fake_project
        # Central config with uploads enabled
        central_data = {
            "shared_files": [],
            "uploads": {"allowed": True, "paths": ["contributions/**/*.md"]},
        }
        _write_config(shared_dir, _make_config(mode="central"))

        # Create a new file in shared dir
        contrib = shared_dir / "contributions"
        contrib.mkdir()
        (contrib / "new.md").write_text("# New")

        stub = StubGitOps(fetch_file_result=json.dumps(central_data).encode())
        messages = push_files(
            project_root=root, dry_run=True,
            _detect_identity=_stub_detect_identity,
            _fetch_file=stub.fetch_single_file,
        )
        assert any("[dry-run] Would upload:" in m and "new.md" in m for m in messages)

    def test_dry_run_shows_denied_files(self, fake_project):
        root, shared_dir = fake_project
        central_data = {
            "shared_files": [],
            "uploads": {"allowed": True, "paths": ["contributions/**/*.md"]},
        }
        _write_config(shared_dir, _make_config(mode="central"))

        # File that doesn't match any upload pattern
        (shared_dir / "rogue.txt").write_text("nope")

        stub = StubGitOps(fetch_file_result=json.dumps(central_data).encode())
        messages = push_files(
            project_root=root, dry_run=True,
            _detect_identity=_stub_detect_identity,
            _fetch_file=stub.fetch_single_file,
        )
        assert any("DENIED" in m and "rogue.txt" in m for m in messages)

    def test_upload_files_included_in_push(self, fake_project):
        root, shared_dir = fake_project
        central_data = {
            "shared_files": [],
            "uploads": {"allowed": True, "paths": ["*.md"]},
        }
        _write_config(shared_dir, _make_config(mode="central"))
        (shared_dir / "new-doc.md").write_text("# New Doc")

        stub = StubGitOps(fetch_file_result=json.dumps(central_data).encode())
        messages = push_files(
            project_root=root, force=True,
            _detect_identity=_stub_detect_identity,
            _fetch_file=stub.fetch_single_file,
            _sparse_checkout=stub.sparse_checkout_files,
            _cleanup=stub.cleanup,
            _push=stub.push_files,
        )

        assert stub.push_called
        assert "new-doc.md" in stub.push_kwargs["file_map"]
        assert any("OK: pushed new-doc.md" in m for m in messages)


# ===========================================================================
# Multi-project tests
# ===========================================================================


class TestMultiProjectGetAndPush:
    """Tests for --project selection in get/push."""

    def _multi_config(self, default=None):
        config: dict = {
            "projects": {
                "auth": {
                    "source_repo": {"url": "https://example.com/auth.git"},
                    "shared_files": [
                        {"remote_path": "guide.md", "local_path": "guide.md", "action": "get"}
                    ],
                },
                "agent": {
                    "source_repo": {"url": "https://example.com/agent.git"},
                    "shared_files": [
                        {"remote_path": "spec.md", "local_path": "spec.md", "action": "get"}
                    ],
                },
            },
        }
        if default:
            config["default_project"] = default
        return config

    def test_get_with_project_selects_correct_source(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, self._multi_config())

        stub = StubGitOps(
            remote_shas={"spec.md": "sha1"},
            sparse_files={"spec.md": b"# Agent Spec"},
        )
        messages = get_files(
            project_root=root, project="agent",
            _get_shas=stub.get_remote_blob_shas,
            _sparse_checkout=stub.sparse_checkout_files,
            _read_clone=stub.read_file_from_clone,
            _cleanup=stub.cleanup,
        )
        assert any("OK" in m and "spec.md" in m for m in messages)
        # File lands under the agent/ subdirectory
        assert (shared_dir / "agent" / "spec.md").exists()

    def test_get_dry_run_with_default_project(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, self._multi_config(default="auth"))

        stub = StubGitOps(remote_shas={"guide.md": "sha1"})
        messages = get_files(
            project_root=root, dry_run=True,
            _get_shas=stub.get_remote_blob_shas,
        )
        assert any("[dry-run]" in m and "guide.md" in m for m in messages)

    def test_get_raises_without_project_or_default(self, fake_project):
        root, shared_dir = fake_project
        _write_config(shared_dir, self._multi_config())

        with pytest.raises(ValueError, match="No --project specified"):
            get_files(project_root=root)

    def test_push_with_project_selects_correct_source(self, fake_project):
        root, shared_dir = fake_project
        config = {
            "projects": {
                "alpha": {
                    "source_repo": {"url": "https://example.com/alpha.git"},
                    "shared_files": [
                        {"remote_path": "docs/a.md", "local_path": "a.md", "action": "push"}
                    ],
                },
            },
            "default_project": "alpha",
        }
        _write_config(shared_dir, config)
        # File must be at the auto-prefixed location: alpha/a.md
        (shared_dir / "alpha").mkdir()
        (shared_dir / "alpha" / "a.md").write_text("# Alpha doc")

        stub = StubGitOps()
        messages = push_files(
            project_root=root, force=True, project="alpha",
            _sparse_checkout=stub.sparse_checkout_files,
            _cleanup=stub.cleanup,
            _push=stub.push_files,
        )
        assert stub.push_called
        assert stub.push_kwargs["url"] == "https://example.com/alpha.git"

    def test_projects_isolate_into_separate_subdirectories(self, fake_project):
        """Files from different projects land in separate subdirs."""
        root, shared_dir = fake_project
        _write_config(shared_dir, self._multi_config())

        # Fetch from "auth" project
        stub_auth = StubGitOps(
            remote_shas={"guide.md": "sha1"},
            sparse_files={"guide.md": b"# Auth Guide"},
        )
        get_files(
            project_root=root, project="auth",
            _get_shas=stub_auth.get_remote_blob_shas,
            _sparse_checkout=stub_auth.sparse_checkout_files,
            _read_clone=stub_auth.read_file_from_clone,
            _cleanup=stub_auth.cleanup,
        )

        # Fetch from "agent" project
        stub_agent = StubGitOps(
            remote_shas={"spec.md": "sha2"},
            sparse_files={"spec.md": b"# Agent Spec"},
        )
        get_files(
            project_root=root, project="agent",
            _get_shas=stub_agent.get_remote_blob_shas,
            _sparse_checkout=stub_agent.sparse_checkout_files,
            _read_clone=stub_agent.read_file_from_clone,
            _cleanup=stub_agent.cleanup,
        )

        # Each project's files are in their own subdirectory
        assert (shared_dir / "auth" / "guide.md").read_bytes() == b"# Auth Guide"
        assert (shared_dir / "agent" / "spec.md").read_bytes() == b"# Agent Spec"
