# tlc-shared-docs — Publish & Install Runbook

Quick operator reference. For full documentation see [README.md](README.md)
(consumer side) and [README_CENTRAL.md](README_CENTRAL.md) (central side).

---

## PUBLISH (release a new version to PyPI)

From the repo root (`c:\_code\tlc-doc-share`):

```bash
# 1. Bump the version in BOTH files (keep them identical):
#    - pyproject.toml            -> version = "1.1.0045"
#    - tlc_shared_docs/__init__.py -> __version__ = "1.1.0045"

# 2. Verify before shipping
poetry run pytest -m "not integration"
poetry run flake8 tlc_shared_docs/ tests/
poetry run mypy tlc_shared_docs/

# 3. Commit and push the source
git add -A
git commit -m "v1.1.0045: <what changed>"
git push origin master

# 4. Build and publish to PyPI
poetry build
poetry publish
```

Notes:

- There is **no CI publish step** — `poetry publish` from this machine is the
  release. A version bump is not live until it runs.
- PyPI normalizes the leading zero: `1.1.0045` appears as `1.1.45`. Same
  release, cosmetic only.
- The new version can take a minute to propagate through PyPI's CDN — if a
  fresh install grabs the previous version, retry with an explicit pin
  (see below).

---

## FORCE INSTALL (replace the version on a machine)

```bash
pip install --force-reinstall --no-cache-dir tlc-shared-docs

# If PyPI propagation lag hands you the old version, pin it:
pip install --force-reinstall --no-cache-dir tlc-shared-docs==1.1.45

# Verify
tlc-shared-docs --version
```

---

## ADD TO A PROJECT (consumer repo — pulls docs from a central repo)

Run inside the consumer repo:

```bash
# 1. Install the CLI (if not already on the machine)
pip install tlc-shared-docs

# 2. Install the Claude agent skill (player2 = consumer role).
#    Re-run this after every tlc-shared-docs upgrade — skill files
#    do not update themselves.
tlc-shared-docs init --skill player2
```

Then create `docs/source/shared/shared.json` pointing at the central repo:

```json
{
  "projects": {
    "<project-name>": {
      "source_repo": { "url": "https://github.com/<org>/<central-repo>.git" },
      "mode": "central"
    }
  },
  "default_project": "<project-name>"
}
```

And pull:

```bash
tlc-shared-docs get --dry-run   # preview
tlc-shared-docs get             # fetch
```

The central repo must already have a config entry for this consumer
(see ADD TO CENTRAL below) — without it, `get` reports the central config
as not found.

---

## ADD TO CENTRAL (architecture repo — owns the docs and consumer configs)

Run inside the central/architecture repo:

```bash
# 1. Install the CLI (if not already on the machine)
pip install tlc-shared-docs

# 2. Install the Claude agent skill (player1 = central role).
#    Re-run after every upgrade, same as player2.
tlc-shared-docs init --skill player1
```

Then onboard each consumer by creating `.configs/<org>/<repo>.json`
(the path must match the consumer's git remote exactly):

```json
{
  "shared_files": [
    { "remote_path": "docs/guide.md", "local_path": "guide.md", "action": "get" },
    { "remote_path": "docs/api-spec.md", "local_path": "/docs/api-spec.md", "action": "push" }
  ]
}
```

Push-entry rules (see the player1 skill for details):

- `push` entries need a **leading `/`** on `local_path` — the document lives
  in the consumer's own tracked tree, never under `docs/source/shared/`.
- **One owner per document** — never list the same `remote_path` with both
  `get` and `push`.

For a fellow architecture repo, grant peer access instead of a file list:

```json
{ "type": "peer", "access": "*" }
```

Commit and push — config changes take effect on the consumer's next `get`.
