# Central Mode Setup Guide

This guide walks through setting up **central mode** for `tlc-shared-docs`, where an architecture repo controls what documentation each consumer repo receives.

## Overview

In central mode, the **architecture repo** (the "source") contains:
- The shared documentation files themselves
- A `.configs/` directory with per-consumer-repo config files that define what each consumer gets

**Consumer repos** (e.g., `tlc-core`, `tlc-storage`, `agent-coder`) only need a minimal `shared.json` pointing at the architecture repo. The architecture repo decides what files each consumer receives, what they can upload, and where files are placed.

## How identity detection works

When a consumer runs `tlc-shared-docs get`, the tool automatically determines which config file to fetch:

1. Reads the consumer repo's git `origin` remote URL
2. Extracts the `org/repo` identifier (e.g., `https://github.com/L337-ai/tlc-core.git` becomes `L337-ai/tlc-core`)
3. Fetches `.configs/L337-ai/tlc-core.json` from the architecture repo

This means **no manual identity configuration** is needed on the consumer side. The tool derives the consumer's identity from git.

Supported URL formats:
| Format | Extracted identity |
|---|---|
| `https://github.com/L337-ai/tlc-core.git` | `L337-ai/tlc-core` |
| `https://github.com/L337-ai/tlc-core` | `L337-ai/tlc-core` |
| `git@github.com:L337-ai/tlc-core.git` | `L337-ai/tlc-core` |
| `ssh://git@github.com/L337-ai/tlc-core.git` | `L337-ai/tlc-core` |

## Step 1: Set up the architecture repo

Create an architecture repo (e.g., `agent-coder-arch`) with the following structure:

```
agent-coder-arch/
├── docs/
│   ├── architecture.md
│   ├── api-spec.md
│   └── data-model.md
├── guides/
│   └── onboarding.md
└── .configs/
    └── L337-ai/
        ├── tlc-core.json
        ├── tlc-storage.json
        └── agent-coder.json
```

The shared documentation lives at the top level (or wherever you organize it). The `.configs/` directory contains one JSON file per consumer repo, keyed by `org/repo`.

## Step 2: Create per-consumer config files

Each config file in `.configs/org/repo.json` tells that consumer what to get and push.

**Example: `.configs/L337-ai/tlc-core.json`**

```json
{
  "shared_files": [
    {
      "remote_path": "docs/architecture.md",
      "local_path": "architecture.md",
      "action": "get"
    },
    {
      "remote_path": "docs/data-model.md",
      "local_path": "data-model.md",
      "action": "get"
    },
    {
      "remote_path": "guides/onboarding.md",
      "local_path": "onboarding.md",
      "action": "get"
    }
  ]
}
```

**Example: `.configs/L337-ai/agent-coder.json`** (with push access and uploads)

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
      "contributions/**/*.md"
    ]
  }
}
```

### Config file fields

| Field | Description |
|---|---|
| `shared_files[].remote_path` | Path to the file in the architecture repo |
| `shared_files[].local_path` | Where the file lands in the consumer's `docs/source/shared/<project>/` directory |
| `shared_files[].action` | `get` (consumer pulls) or `push` (consumer pushes back) |
| `uploads.allowed` | Enable auto-upload of new files from this consumer |
| `uploads.paths` | Glob patterns controlling which new files the consumer may upload |

### Glob patterns in get

You can use wildcards in `remote_path` for `get` actions:

```json
{
  "remote_path": "docs/**/*.md",
  "local_path": "docs",
  "action": "get"
}
```

This fetches all `.md` files under `docs/` recursively.

## Step 3: Set up the consumer repo

In the consumer repo (e.g., `tlc-core`), create `docs/source/shared/shared.json`:

### Single-project consumer

If this consumer only participates in one architecture project:

```json
{
  "source_repo": {
    "url": "https://github.com/L337-ai/agent-coder-arch.git",
    "branch": "main"
  },
  "mode": "central"
}
```

### Multi-project consumer

If this consumer participates in multiple architecture projects:

```json
{
  "projects": {
    "agent-coder": {
      "source_repo": {
        "url": "https://github.com/L337-ai/agent-coder-arch.git",
        "branch": "main"
      },
      "mode": "central"
    },
    "auth": {
      "source_repo": {
        "url": "https://github.com/L337-ai/tlc-auth-arch.git",
        "branch": "main"
      },
      "mode": "central"
    }
  },
  "default_project": "agent-coder"
}
```

In multi-project mode, files are automatically isolated into subdirectories:

```
docs/source/shared/
├── shared.json
├── agent-coder/
│   ├── architecture.md
│   └── data-model.md
└── auth/
    └── auth-guide.md
```

## Step 4: Consumer usage

```bash
# See available projects (multi-project only)
tlc-shared-docs list

# Pull shared docs
tlc-shared-docs get                        # uses default_project
tlc-shared-docs get -p agent-coder         # explicit project

# Preview before pulling
tlc-shared-docs get --dry-run

# Push changes back to the architecture repo
tlc-shared-docs push
tlc-shared-docs push --force               # skip conflict check

# Preview before pushing
tlc-shared-docs push --dry-run
```

## The full flow

Here's what happens end-to-end when a consumer runs `tlc-shared-docs get -p agent-coder`:

```
Consumer (tlc-core)                          Arch repo (agent-coder-arch)
─────────────────                            ────────────────────────────

1. Read shared.json
   → project "agent-coder"
   → source: agent-coder-arch.git

2. Read git remote origin
   → "L337-ai/tlc-core"

3. Fetch .configs/L337-ai/tlc-core.json  ──→  Returns the consumer's
                                               file list and permissions

4. Parse shared_files from
   central config

5. Check blob SHAs (skip
   unchanged files)

6. Sparse checkout only the
   files that changed           ←──────────  Only requested blobs
                                              are downloaded

7. Write files to
   docs/source/shared/agent-coder/
```

## Managing permissions

### Read-only consumers

Give a consumer only `get` actions — they can pull docs but not push anything:

```json
{
  "shared_files": [
    { "remote_path": "docs/guide.md", "local_path": "guide.md", "action": "get" }
  ]
}
```

### Read-write consumers

Add `push` actions for files the consumer owns or co-maintains:

```json
{
  "shared_files": [
    { "remote_path": "docs/guide.md", "local_path": "guide.md", "action": "get" },
    { "remote_path": "docs/api-spec.md", "local_path": "api-spec.md", "action": "push" }
  ]
}
```

### Allowing new file uploads

Enable `uploads` with path patterns to let consumers contribute new files:

```json
{
  "shared_files": [],
  "uploads": {
    "allowed": true,
    "paths": [
      "contributions/tlc-core/**/*.md",
      "diagrams/tlc-core/**/*.png"
    ]
  }
}
```

New files placed under `docs/source/shared/<project>/` that match the patterns will be uploaded on `push`. Files that don't match any pattern produce a `DENIED:` warning.

### Denying uploads

Either omit the `uploads` section entirely, or set `"allowed": false`.

## Overriding with --central

You can bypass the `mode` field in `shared.json` by passing `--central` on the command line:

```bash
tlc-shared-docs get --central https://github.com/L337-ai/agent-coder-arch.git
```

This is useful for testing a new architecture repo before updating the consumer's `shared.json`.

## Tips

- **SHA-based skipping**: Files that haven't changed on the remote are automatically skipped. No need to re-download everything on each run.
- **Conflict detection**: `push` checks if remote files have changed since your last pull. Use `--force` only when you're sure you want to overwrite.
- **Dry-run everything**: Always preview with `--dry-run` before your first real run to verify the config is correct.
- **One config change, all consumers update**: When you modify a consumer's `.configs/org/repo.json` in the architecture repo, every future `get` by that consumer picks up the new file list automatically.
