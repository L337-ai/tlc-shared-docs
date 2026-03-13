"""Claude agent skill content for tlc-shared-docs.

Each skill targets a specific role:
- ``player1``: For architecture/shared-docs repos that control consumer configs
- Future: ``player2`` for repos that consume shared docs
"""

# Each skill is (filename, content, claude_md_stub)
SKILLS: dict[str, tuple[str, str, str]] = {}

# ---------------------------------------------------------------------------
# Player 1 skill — for the architecture repo that owns .configs/
# ---------------------------------------------------------------------------

_PLAYER1_STUB = """\

## tlc-shared-docs (central repo)

This is a central architecture repo that distributes shared documentation to
consumer repos via `tlc-shared-docs`.

When the user mentions shared docs, shared documents, shared-docs, shared files,
document sharing, doc sharing, `.configs/`, consumer configs, or `tlc-shared-docs`,
read `.claude/tlc-shared-docs-player1.md` for detailed instructions before proceeding.
"""

SKILLS["player1"] = ("tlc-shared-docs-player1.md", """\
# tlc-shared-docs — Central Repo Agent Instructions

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
.configs/                          ← Per-consumer config files
├── <org>/
│   ├── <consumer-repo-1>.json     ← What consumer-repo-1 gets/pushes
│   ├── <consumer-repo-2>.json
│   └── ...
docs/                              ← The shared documentation itself
├── architecture.md
├── api-spec.md
└── ...
```

### How consumers are identified

When a consumer runs `tlc-shared-docs get`, the tool:
1. Reads the consumer's git remote origin URL
2. Extracts `org/repo` (e.g., `https://github.com/L337-ai/tlc-core.git` → `L337-ai/tlc-core`)
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

### local_path behavior

On the consumer side, files are auto-isolated into a project subdirectory.
If the consumer's `shared.json` uses multi-project mode with project name
`agent-coder`, a file with `"local_path": "guide.md"` lands at
`docs/source/shared/agent-coder/guide.md` on their side.

You do NOT need to prefix `local_path` with the project name — that happens
automatically on the consumer side.

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
""", _PLAYER1_STUB)
