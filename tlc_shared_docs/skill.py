"""Claude agent skill content for tlc-shared-docs.

Each skill targets a specific role:
- ``player1``: For architecture/shared-docs repos that control consumer configs
- ``player2``: For consumer repos that pull/push shared docs from an arch repo

The CLAUDE.md stub is generic and shared across all skills. It uses HTML
comment markers so it can be found and replaced idempotently. The stub
directs Claude to read all ``.claude/tlc-shared-docs-*.md`` files.
"""

import re
from pathlib import Path

# Each skill is (filename, content)
SKILLS: dict[str, tuple[str, str]] = {}

# ---------------------------------------------------------------------------
# Shared CLAUDE.md stub — generic, never needs updating
# ---------------------------------------------------------------------------

_MARKER_START = "<!-- tlc-shared-docs -->"
_MARKER_END = "<!-- /tlc-shared-docs -->"

CLAUDE_MD_STUB = f"""{_MARKER_START}

## tlc-shared-docs

This project uses `tlc-shared-docs` for shared documentation artefacts.

When the user mentions shared docs, shared documents, shared-docs, shared files,
document sharing, doc sharing, doc sync, `.configs/`, consumer configs, architecture
docs, arch docs, or `tlc-shared-docs`, read **all** `.claude/tlc-shared-docs-*.md`
files for instructions before proceeding.

{_MARKER_END}
"""


def install_claude_md_stub(project_root: Path) -> str:
    """Insert or replace the tlc-shared-docs block in CLAUDE.md.

    Returns a status message describing what was done.
    """
    claude_md = project_root / "CLAUDE.md"
    existing = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""

    # If markers exist, replace the block between them
    pattern = re.compile(
        re.escape(_MARKER_START) + r".*?" + re.escape(_MARKER_END),
        re.DOTALL,
    )
    if pattern.search(existing):
        updated = pattern.sub(CLAUDE_MD_STUB.strip(), existing)
        claude_md.write_text(updated, encoding="utf-8")
        return "Updated:   CLAUDE.md (replaced tlc-shared-docs block)"

    # No markers — append the stub
    with open(claude_md, "a", encoding="utf-8") as f:
        f.write(CLAUDE_MD_STUB)
    return "Updated:   CLAUDE.md (added tlc-shared-docs block)"


# ---------------------------------------------------------------------------
# Player 1 — architecture repo that owns .configs/ and shared docs
# ---------------------------------------------------------------------------

SKILLS["player1"] = ("tlc-shared-docs-player1.md", """\
# tlc-shared-docs — Central Repo Agent Instructions (Player 1)

This is an **architecture repo** (central repo) that distributes shared
documentation to consumer repos via `tlc-shared-docs`. This file tells you
how this repo is structured and how to manage it.

---

## Your role

This repo is the **source of truth** for shared documentation. Consumer repos
(e.g., `tlc-core`, `tlc-storage`, `agent-coder`) pull files FROM this repo.
You control what each consumer receives by editing config files in `.configs/`.

---

## Repo structure

```
.configs/                          <- Per-consumer config files
├── <org>/
│   ├── <consumer-repo-1>.json     <- What consumer-repo-1 gets/pushes
│   ├── <consumer-repo-2>.json
│   └── ...
docs/                              <- The shared documentation itself
├── architecture.md
├── api-spec.md
└── ...
```

### How consumers are identified

When a consumer runs `tlc-shared-docs get`, the tool:
1. Reads the consumer's git remote origin URL
2. Extracts `org/repo` (e.g., `https://github.com/L337-ai/tlc-core.git` -> `L337-ai/tlc-core`)
3. Fetches `.configs/L337-ai/tlc-core.json` from THIS repo

The config file path is derived automatically — consumers don't configure it.

---

## Consumer config files (.configs/org/repo.json)

Each file defines what that consumer can get and push:

```json
{
  "shared_files": [
    {
      "remote_path": "docs/architecture.md",
      "local_path": "architecture.md",
      "action": "get"
    },
    {
      "remote_path": "docs/api-spec.md",
      "local_path": "api-spec.md",
      "action": "push"
    }
  ],
  "uploads": {
    "allowed": true,
    "paths": [
      "contributions/<consumer-name>/**/*.md"
    ]
  }
}
```

### Fields

| Field | Description |
|---|---|
| `shared_files[].remote_path` | Path to the file IN THIS REPO |
| `shared_files[].local_path` | Where the file lands on the consumer side (relative to their shared dir) |
| `shared_files[].action` | `get` = consumer pulls from here. `push` = consumer pushes back here |
| `uploads.allowed` | Whether the consumer can upload new files |
| `uploads.paths` | Glob patterns restricting where new uploads may land |

### local_path and project-id prefixing

On the consumer side, files are auto-isolated into a project subdirectory.
If the consumer's `shared.json` uses multi-project mode with project name
`agent-coder`, a file with `"local_path": "guide.md"` lands at
`docs/source/shared/agent-coder/guide.md` on their side.

**Prefixing is automatic and idempotent.** The tool prepends the project
name to `local_path` UNLESS it already starts with the project name. Both
of these produce identical results on the consumer side:

- `"local_path": "guide.md"` -> `agent-coder/guide.md` (auto-prefixed)
- `"local_path": "agent-coder/guide.md"` -> `agent-coder/guide.md` (already prefixed, skipped)

**Best practice:** Use short paths like `"guide.md"` and let the tool
prefix automatically. Only use the full path if you need to be explicit.

### Glob patterns in remote_path

You can use wildcards for `get` actions:
- `docs/**/*.md` — all markdown files under docs/ recursively
- `guides/*.md` — markdown files in guides/ (one level)
- `*.md` — all markdown at the root

---

## Key rules for agents working in this repo

1. **Understand the consumer before editing their config.** Read the existing
   `.configs/org/repo.json` file before modifying it. Know what files they
   currently receive.

2. **`remote_path` refers to paths in THIS repo.** Make sure the file
   actually exists here before adding it to a consumer's config.

3. **Adding a new consumer:** Create `.configs/<org>/<repo>.json` with the
   appropriate `shared_files` entries. The org/repo must match the consumer's
   git remote origin exactly.

4. **Removing a consumer's access to a file:** Remove the entry from their
   config. The file stays in this repo — it just stops being sent to them.

5. **Upload permissions are restrictive by default.** Only add `uploads`
   when you explicitly want a consumer to contribute files back. Use tight
   glob patterns (e.g., `contributions/tlc-core/**/*.md`) rather than broad
   ones (e.g., `**/*`).

6. **Do not delete documentation files** without checking which consumers
   reference them. Search all `.configs/` files for the `remote_path` first:
   ```bash
   grep -r "filename.md" .configs/
   ```

7. **Test with dry-run.** Consumer repos can preview what they'd receive:
   ```bash
   tlc-shared-docs get --dry-run
   ```

8. **Config changes take effect immediately.** When you commit a change to
   a `.configs/org/repo.json` file, the next time that consumer runs
   `tlc-shared-docs get`, they receive the updated file list. There is no
   deploy step.

---

## Common tasks

### Give a consumer access to a new file

Edit `.configs/<org>/<repo>.json` and add an entry:
```json
{ "remote_path": "docs/new-guide.md", "local_path": "new-guide.md", "action": "get" }
```

### Let a consumer push changes to a file

Set `action` to `push`:
```json
{ "remote_path": "docs/api-spec.md", "local_path": "api-spec.md", "action": "push" }
```

### Allow a consumer to upload new files

Add an `uploads` section:
```json
"uploads": {
  "allowed": true,
  "paths": ["contributions/consumer-name/**/*.md"]
}
```

### Onboard a new consumer repo

1. Determine their `org/repo` from their git remote (e.g., `L337-ai/new-service`)
2. Create `.configs/L337-ai/new-service.json`
3. Add the appropriate `shared_files` entries
4. Commit and push — the consumer can now run `tlc-shared-docs get`

### Check who receives a specific file

```bash
grep -r "architecture.md" .configs/
```
""")

# ---------------------------------------------------------------------------
# Player 2 — consumer repo that pulls/pushes shared docs from an arch repo
# ---------------------------------------------------------------------------

SKILLS["player2"] = ("tlc-shared-docs-player2.md", """\
# tlc-shared-docs — Consumer Repo Agent Instructions (Player 2)

This repo **consumes** shared documentation from one or more architecture
repos via `tlc-shared-docs`. This file tells you how to work with shared
docs in this repo.

> **If this repo also has a player1 skill installed** (i.e., it is ALSO an
> architecture repo), ask the user to clarify: "Did you mean the shared docs
> managed by this repo, or the ones consumed from a remote?" Do not guess.

---

## Your role

This repo pulls documentation FROM architecture repos and optionally pushes
changes back. You do NOT control what files are available — the architecture
repo decides that via its `.configs/` directory.

---

## Config location

The config is at `docs/source/shared/shared.json`. Read this file FIRST to
understand which projects and sources are configured.

---

## Config formats

### Single-source (legacy)

```json
{
  "source_repo": {
    "url": "https://github.com/org/arch-repo.git",
    "branch": "main"
  },
  "mode": "central"
}
```

### Multi-project

```json
{
  "projects": {
    "agent-coder": {
      "source_repo": { "url": "https://github.com/org/agent-coder-arch.git" },
      "mode": "central"
    },
    "auth": {
      "source_repo": { "url": "https://github.com/org/tlc-auth-arch.git" },
      "mode": "central"
    }
  },
  "default_project": "agent-coder"
}
```

---

## Where shared files live

In multi-project mode, files are auto-isolated into subdirectories
named after the project-id:

```
docs/source/shared/
├── shared.json
├── agent-coder/         <- files from the agent-coder project
│   ├── architecture.md
│   └── api-spec.md
└── auth/                <- files from the auth project
    └── guide.md
```

In single-source mode, files land directly under `docs/source/shared/`.

### Project-id prefixing

The tool automatically prepends the project name to each file's
`local_path`. This happens idempotently — if the central config
already includes the project name in the path (e.g.,
`"local_path": "agent-coder/guide.md"`), it will NOT double-prefix.
Both `"guide.md"` and `"agent-coder/guide.md"` resolve to
`docs/source/shared/agent-coder/guide.md`.

**When referencing shared files in this repo, always use the full
path including the project subdirectory** (e.g.,
`docs/source/shared/agent-coder/guide.md`).

---

## CLI commands

```bash
# See what projects are available
tlc-shared-docs list

# Pull shared docs (uses default_project or specify one)
tlc-shared-docs get
tlc-shared-docs get -p agent-coder

# Preview before pulling
tlc-shared-docs get --dry-run

# Push changes back to the architecture repo
tlc-shared-docs push
tlc-shared-docs push --force

# Preview before pushing
tlc-shared-docs push --dry-run
```

---

## Key rules for agents working in this repo

1. **Always read `docs/source/shared/shared.json` first** to understand the
   config before running any tlc-shared-docs commands.

2. **Use `--dry-run` before real operations** to verify what will happen.

3. **Use `-p PROJECT` when multi-project** — run `tlc-shared-docs list`
   to see available projects if unsure.

4. **Shared files are gitignored by default.** The `.gitignore` in
   `docs/source/shared/` excludes everything except `shared.json`. Do not
   commit fetched docs unless the `.gitignore` has been modified to allow it.

5. **Do not manually edit files in `docs/source/shared/<project>/`** that
   were fetched via `get`. They will be overwritten on the next pull.

6. **To contribute new files** (when uploads are enabled by the architecture
   repo), place them in the appropriate project subdirectory and run
   `tlc-shared-docs push`. The architecture repo's central config controls
   which paths are permitted — files outside those patterns are denied.

7. **Conflict handling**: If `push` reports a CONFLICT, do not use `--force`
   without understanding what changed on the remote. Run `get` first to pull
   the latest, then resolve and push again.

8. **Never modify `docs/source/shared/shared.json` without being asked.**
   This is a coordination file shared across the team.

9. **You cannot control what files are available.** The architecture repo
   (player 1) manages the `.configs/` directory that determines what this
   repo gets. If the user wants access to a new file, tell them to update
   the consumer config in the architecture repo.

---

## Common tasks

### Pull the latest shared docs

```bash
tlc-shared-docs get -p <project-name>
```

### Check what's available

```bash
tlc-shared-docs list
tlc-shared-docs get --dry-run -p <project-name>
```

### Upload a new file to the architecture repo

1. Place the file under `docs/source/shared/<project>/` in a path that
   matches the upload patterns configured by the architecture repo.
2. Preview: `tlc-shared-docs push --dry-run`
3. If permitted: `tlc-shared-docs push`
4. If denied: ask the user to request upload access from the architecture
   repo maintainer.

### Check which project a file belongs to

Look at which subdirectory it's under in `docs/source/shared/`. Each
subdirectory corresponds to a project name in `shared.json`.
""")
