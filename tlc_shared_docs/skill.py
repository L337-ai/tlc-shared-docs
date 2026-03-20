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
| `type` | `"project"` (default) or `"peer"` — marks this consumer as a fellow architecture repo rather than a standard project repo |
| `shared_files[].remote_path` | Path to the file IN THIS REPO |
| `shared_files[].local_path` | Where the file lands on the consumer side (relative to their shared dir) |
| `shared_files[].action` | `get` = consumer pulls from here. `push` = consumer pushes back here |
| `uploads.allowed` | Whether the consumer can upload new files |
| `uploads.paths` | Glob patterns restricting where new uploads may land |

### Peer consumers

A **peer** is a fellow architecture repo that subscribes to this repo. Unlike
project consumers (where YOU control the file list), a peer controls its own
file list in its own `shared.json` — your `.configs/` entry just grants access.

**Your config for a peer is minimal:**

```json
{
  "type": "peer",
  "access": "*"
}
```

That's it. No `shared_files` — the peer decides what it needs. Your file
grants blanket access to everything in this repo. To restrict access to a
specific folder, use a glob:

```json
{
  "type": "peer",
  "access": "repo_docs/**"
}
```

**How peer access differs from project access:**

| | Project consumer | Peer consumer |
|---|---|---|
| File list controlled by | This repo (`.configs/` entry) | The peer's own `shared.json` |
| Your config needs | Full `shared_files` list | Just `type: peer` + `access` |
| Peer can request any file? | No — only what you listed | Yes (within `access` scope) |
| Peer can use bundles? | N/A — you reference bundles for them | Yes — peer lists `{"bundle": "name"}` in their own `shared.json` |

`project` consumers are end-product repos; `peer` consumers are sibling
architecture repos consuming shared standards or patterns internally.

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

9. **Consumer `shared.json` is auto-updated on every `get`.** When a
   consumer runs `get` in central mode, the tool writes the resolved
   `shared_files` list back into their local `shared.json`. This means
   their AI agent can read `shared.json` to know exactly which files they
   are responsible for syncing. You do not need to tell consumers what
   files they have — they can always check `shared.json` after a `get`.

10. **Removing files from a consumer's list** does not delete them on the
    consumer side. Old files remain until the consumer runs
    `tlc-shared-docs get --clean`. Tell consumers to use `--clean` after
    you remove entries from their config.

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

### Grant peer access to a fellow architecture repo

Use this when another arch repo needs access to pull from this repo for
internal use. Unlike project consumers, the peer controls its own file list —
you just grant access.

**"Give REPO peer access to everything"**

Determine their `org/repo` from their git remote, then create
`.configs/<org>/<repo>.json`:
```json
{
  "type": "peer",
  "access": "*"
}
```
Commit and push. The peer can now request any file in this repo via its own
`shared.json` entries.

**"Give REPO peer access to just FOLDER"**

Use a glob pattern to scope the grant:
```json
{
  "type": "peer",
  "access": "repo_docs/**"
}
```
The peer may only request files matching `repo_docs/**`. Requests outside
that scope are denied and reported at get-time. Commit and push.

### Check who receives a specific file

```bash
grep -r "architecture.md" .configs/
```

---

## Bundles

Bundles are named, reusable collections of files defined in `.configs/bundles/`.
Use them when many consumers share the same set of docs — instead of
copy-pasting the same list into every consumer config, define the list once
and reference it by name.

### Creating a bundle

Create `.configs/bundles/<bundle-name>.json` in this repo:

```json
{
  "description": "Standard agent skills and process docs",
  "shared_files": [
    { "remote_path": "docs/coding-standards.md", "local_path": "coding-standards.md" },
    { "remote_path": "docs/sprint-process.md",   "local_path": "process/sprint.md" },
    { "remote_path": "docs/api-patterns.md",     "local_path": "api-patterns.md" }
  ]
}
```

**No `action` field** — bundle files are always `get`. Do not add `"action"` to
bundle entries; it is implied.

### Who can reference a bundle?

Bundles are always stored in THIS repo (`.configs/bundles/`). Any consumer
can reference them — **project consumers AND peer consumers** — but they do
so in different places:

| Consumer type | Where the bundle ref goes | Who writes it |
|---|---|---|
| **Project** | `.configs/org/repo.json` in THIS repo | You (Player 1) |
| **Peer** | The peer's own `shared.json` | The peer (Player 2) |

### For project consumers: reference bundles in your config entry

In `.configs/org/repo.json`, mix bundle references with individual files:

```json
{
  "shared_files": [
    { "bundle": "skills-and-process" },
    { "bundle": "architecture-patterns" },
    { "remote_path": "docs/consumer-specific.md", "local_path": "specific.md", "action": "get" }
  ]
}
```

When the project consumer runs `tlc-shared-docs get`, the tool fetches and
inlines all bundle files alongside the individual entries.

### For peer consumers: they reference bundles themselves

Peer consumers write `{"bundle": "name"}` directly in their own `shared.json`.
Your only responsibility is ensuring:
1. The bundle file exists at `.configs/bundles/name.json` (committed and pushed)
2. The peer's access grant covers the files in the bundle

```json
{
  "type": "peer",
  "access": "*"
}
```

The peer then controls everything else from their side. See Player 2 docs for details.

### Deduplication

Duplicate files (same `remote_path` AND same `local_path`) are silently
dropped — safe to reference overlapping bundles. The same file to a different
local destination is kept (two destinations = two fetches = both valid).

### Naming conventions

- Use kebab-case: `skills-and-process`, `architecture-patterns`
- One bundle per concern — keep them focused so consumers can mix and match
- Document the bundle's purpose in the `"description"` field

### Audit which consumers use a bundle

```bash
grep -r "\"bundle\": \"skills-and-process\"" .configs/
```

### Troubleshooting a missing bundle

If a consumer reports `WARNING: Bundle 'name' not found`, check:
1. The file exists at `.configs/bundles/name.json` in this repo
2. It is committed and pushed to the branch the consumer is pointed at
3. The bundle name in the consumer config matches the filename exactly (case-sensitive)
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
    "shared-standards": {
      "source_repo": { "url": "https://github.com/org/standards-arch.git" },
      "mode": "central",
      "type": "peer"
    }
  },
  "default_project": "agent-coder"
}
```

The `"type"` field marks how this repo relates to the source:

| `type` | Meaning | Who controls the file list? |
|---|---|---|
| `"project"` (default) | Consuming from an arch repo that owns this domain | The arch repo — via its `.configs/<org>/<your-repo>.json` |
| `"peer"` | Consuming from a fellow architecture repo | **You** — via your own `shared_files` in this file |

`tlc-shared-docs list` displays `peer` entries with a label so you can tell
them apart at a glance.

---

## Project mode vs Peer mode

### Project mode — arch repo controls the file list

For `"type": "project"` (the default), the architecture repo decides what
you receive by editing its `.configs/<org>/<your-repo>.json`. You do not
list files yourself — `shared.json` stays clean with just the connection config:

```json
{
  "projects": {
    "agent-coder": {
      "source_repo": { "url": "https://github.com/org/arch-repo.git" },
      "mode": "central"
    }
  }
}
```

The arch repo controls what you get and what you push. Run `tlc-shared-docs get`
to pull the current file list. If the arch repo has assigned you any `push` files,
the `get` output will list them — run `tlc-shared-docs push` to send them back.

### Peer mode — you control the file list

For `"type": "peer"`, you are a fellow architecture repo. The other arch repo's
central config just grants you access — your `shared_files` is the request list,
and you own it completely.

```json
{
  "projects": {
    "shared-standards": {
      "source_repo": { "url": "https://github.com/org/standards-arch.git", "branch": "main" },
      "mode": "central",
      "type": "peer",
      "shared_files": [
        { "remote_path": "docs/coding-standards.md", "local_path": "coding-standards.md", "action": "get" },
        { "remote_path": "docs/api-patterns.md",     "local_path": "api-patterns.md",     "action": "get" }
      ]
    }
  }
}
```

In peer mode:
- `shared_files` is **safe to edit manually** — it is never overwritten by `get`
- Add files by `remote_path`, or reference an entire bundle by name (see below)
- The arch repo may restrict access to a specific path. Files outside their
  granted scope are reported as `DENIED` at get-time and excluded from the fetch

### Peer mode with bundles

Instead of listing individual files, a peer can reference a **bundle** — a
named collection of files defined in the arch repo's `.configs/bundles/`:

```json
{
  "projects": {
    "shared-standards": {
      "source_repo": { "url": "https://github.com/org/standards-arch.git" },
      "mode": "central",
      "type": "peer",
      "shared_files": [
        { "bundle": "skills-and-process" },
        { "bundle": "architecture-patterns" },
        { "remote_path": "docs/extra-ref.md", "local_path": "extra-ref.md", "action": "get" }
      ]
    }
  }
}
```

When you run `tlc-shared-docs get -p shared-standards`:
1. The tool fetches the arch repo's peer grant for this repo (`.configs/<org>/<your-repo>.json`)
2. For each `{"bundle": "name"}` entry, it fetches `.configs/bundles/name.json` from the arch repo
3. All files from every bundle (plus any plain entries) are resolved and downloaded
4. Your `shared_files` is NOT overwritten — the bundle references remain intact for next time

**Bundle files are always `get`** — you do not specify an action.

**Dry-run a bundle before pulling:**
```bash
tlc-shared-docs get -p shared-standards --bundle skills-and-process --dry-run
```
This shows `NEW` or `OVERWRITE` per file so you can see exactly what will land
before committing to the fetch.

**Prerequisites for peer + bundle to work:**
- The arch repo has created `.configs/bundles/name.json` and committed it
- The arch repo has granted you peer access: `.configs/<your-org>/<your-repo>.json`
  with `{"type": "peer", "access": "*"}` (or a scoped glob)
- Your project entry has `"mode": "central"` and `"type": "peer"`

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

# Pull multiple projects at once
tlc-shared-docs get -p all                    # every configured project
tlc-shared-docs get -p peers                  # all peer-type projects only
tlc-shared-docs get -p "agent-coder auth"     # specific subset

# Preview before pulling
tlc-shared-docs get --dry-run
tlc-shared-docs get -p all --dry-run

# Preview a single bundle (shows NEW / OVERWRITE per file)
tlc-shared-docs get --bundle skills-and-process --dry-run
tlc-shared-docs get -p agent-coder --bundle skills-and-process --dry-run

# Remove stale files no longer in the share list
tlc-shared-docs get --clean
tlc-shared-docs get -p agent-coder --clean --dry-run
tlc-shared-docs get -p all --clean            # clean across all projects

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

8. **`shared_files` rules differ by type:**
   - **Project mode** (`"type": "project"`): do not add `shared_files` to the config.
     The arch repo controls everything via its `.configs/` entry. `shared.json` is
     never modified by `get` — it stays as the clean connection config you wrote.
   - **Peer mode** (`"type": "peer"`): `shared_files` is YOUR request list.
     Edit it freely — add individual files or `{"bundle": "name"}` references.
     It is never overwritten by `get`.

9. **The `shared_files` list shows which docs need to stay current.**
   After each `get`, read `shared.json` to see which files are in scope.
   Files with `"action": "get"` are owned by the architecture repo; files
   with `"action": "push"` are owned by this repo and must be kept up to
   date as code evolves. When the user makes changes that affect a push
   file, remind them to run `tlc-shared-docs push` to sync.

10. **You cannot control what files are available.** The architecture repo
    (player 1) manages the `.configs/` directory that determines what this
    repo gets. If the user wants access to a new file, tell them to update
    the consumer config in the architecture repo.

11. **Use `--clean` to remove stale files.** If the architecture repo
    removes files from the share list, old copies stay on disk. Run
    `tlc-shared-docs get --clean` to delete files that are no longer in
    the current share list. Use `--clean --dry-run` to preview first.
    Only files in the project subdirectory are scanned; internal files
    and other projects are never touched.

---

## Common tasks

### Pull the latest shared docs

```bash
tlc-shared-docs get -p <project-name>
tlc-shared-docs get -p all               # every configured project
```

### Clean up stale files

```bash
tlc-shared-docs get -p <project-name> --clean --dry-run   # preview
tlc-shared-docs get -p <project-name> --clean              # delete stale files
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

---

## Getting a specific file from an architecture repo

When the user gives you a URL or path and a desired local destination — e.g.:

> "I need https://github.com/L337-ai/tlc-auth-arch/blob/service-account-mvp/003-architecture-reference.md at repo_docs/shared-arch-reference.md"

Follow these steps:

### Step 1 — Parse the request

Extract from the URL or description:
- **Repo URL**: `https://github.com/L337-ai/tlc-auth-arch`
- **Branch**: `service-account-mvp` (the segment after `/blob/`)
- **Remote path**: `003-architecture-reference.md` (everything after the branch)
- **Local path**: `repo_docs/shared-arch-reference.md` (what the user specified)

### Step 2 — Find the project in shared.json

Read `docs/source/shared/shared.json`. Look for a project entry whose
`source_repo.url` matches the repo URL. If found, note its name and `type`.
If not found, treat it as `"project"` type (you have no pre-existing access).

### Step 3 — Check the branch

If the project is configured but its `source_repo.branch` differs from the
branch in the URL, ask the user whether to switch:
```bash
tlc-shared-docs branch service-account-mvp -p <project-name>
```

### Step 4a — If `type` is `"project"` (or repo not yet in shared.json)

You cannot add files to a project consumer's list yourself — the architecture
repo controls it. Tell the user:

> "To get this file, the arch repo maintainer needs to add this entry to
> `.configs/<your-org>/<your-repo>.json` in their repo:"

```json
{
  "remote_path": "003-architecture-reference.md",
  "local_path": "repo_docs/shared-arch-reference.md",
  "action": "get"
}
```

Once they confirm it is added, run:
```bash
tlc-shared-docs get -p <project-name>
```

### Step 4b — If `type` is `"peer"`

You control your own file list. Proceed in three sub-steps:

**1. Add the entry to shared.json** under the project's `shared_files`:
```json
{
  "remote_path": "003-architecture-reference.md",
  "local_path": "repo_docs/shared-arch-reference.md",
  "action": "get"
}
```

**2. Test access with a dry-run:**
```bash
tlc-shared-docs get -p <project-name> --dry-run
```
- If output contains `DENIED` → the file is outside your granted access scope.
  Remove the entry you just added and tell the user to ask the arch repo to
  broaden peer access (e.g., `"access": "*"` or `"access": "003-*"`).
- If output shows the file as a planned fetch → access is confirmed.

**3. Pull the file:**
```bash
tlc-shared-docs get -p <project-name>
```

The file lands at `docs/source/shared/<project-name>/repo_docs/shared-arch-reference.md`
(the project subdirectory is auto-prefixed).
""")
