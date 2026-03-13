"""Command-line interface for tlc-shared-docs."""

from __future__ import annotations

import argparse
import sys

from pathlib import Path

from tlc_shared_docs import __version__
import tlc_shared_docs.config as cfg
from tlc_shared_docs.core import get_files, push_files
from tlc_shared_docs.skill import SKILLS, install_claude_md_stub


_EPILOG = """\
commands:
  get   Pull shared files from the remote repo
        --dry-run              Preview without making changes
        --central URL          Fetch config from a central repo URL
        -p, --project NAME     Select a named project (multi-project configs)

  push  Push local shared files to the remote repo
        --dry-run              Preview without making changes
        --force                Overwrite even if remote files changed
        --central URL          Fetch config from a central repo URL
        -p, --project NAME     Select a named project (multi-project configs)

  list  List available projects defined in shared.json

  init  Install a Claude agent skill file into this repo
        --skill NAME           Skill to install (player1=arch repo, player2=consumer)

examples:
  tlc-shared-docs list                      Show available projects
  tlc-shared-docs get -p agent-coder        Pull docs for a specific project
  tlc-shared-docs get --dry-run             Preview what would be fetched
  tlc-shared-docs push --force              Push and overwrite remote changes
  tlc-shared-docs push -p auth --dry-run    Preview push for a project
  tlc-shared-docs init --skill player1     Install Claude skill for arch repos
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tlc-shared-docs",
        description="Share documentation files between Git repositories.",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    sub = parser.add_subparsers(dest="command")

    # --- get: pull shared files from the remote repo ---
    get_parser = sub.add_parser("get", help="Pull shared files from the remote repo")
    get_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    get_parser.add_argument(
        "--central",
        metavar="URL",
        default=None,
        help="Use central control mode: fetch config from this repo URL",
    )
    get_parser.add_argument(
        "-p", "--project",
        default=None,
        help="Select a named project from shared.json (multi-project configs)",
    )

    # --- push: push local shared files to the remote repo ---
    push_parser = sub.add_parser("push", help="Push local shared files to the remote repo")
    push_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    push_parser.add_argument(
        "--force",
        action="store_true",
        help="Force-push even if remote files have changed",
    )
    push_parser.add_argument(
        "--central",
        metavar="URL",
        default=None,
        help="Use central control mode: fetch config from this repo URL",
    )
    push_parser.add_argument(
        "-p", "--project",
        default=None,
        help="Select a named project from shared.json (multi-project configs)",
    )

    # --- list: show available projects ---
    sub.add_parser("list", help="List available projects in shared.json")

    # --- init: install Claude agent skill files ---
    init_parser = sub.add_parser(
        "init", help="Install a Claude agent skill file into this repo",
    )
    available_skills = ", ".join(sorted(SKILLS.keys()))
    init_parser.add_argument(
        "--skill",
        required=True,
        choices=sorted(SKILLS.keys()),
        help=f"Which skill to install ({available_skills})",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    """Entry point for the CLI. Parses arguments and dispatches to
    the appropriate get/push handler."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    try:
        # Dispatch to the correct command handler
        if args.command == "init":
            filename, content = SKILLS[args.skill]
            root = cfg.find_project_root()

            # Write the skill file to .claude/
            dest = root / ".claude" / filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
            print(f"Installed: {dest.relative_to(root)}")

            # Insert or replace the generic stub in CLAUDE.md
            print(install_claude_md_stub(root))
            return
        elif args.command == "list":
            projects = cfg.list_projects(cfg.find_project_root())
            if not projects:
                print("Single-source config (no named projects).")
            else:
                for p in projects:
                    print(f"  {p['name']}  {p['url']}  ({p['branch']}, {p['mode']})")
            return
        elif args.command == "get":
            messages = get_files(
                dry_run=args.dry_run, central_url=args.central,
                project=args.project,
                _print=lambda m: print(m, flush=True),
            )
        elif args.command == "push":
            messages = push_files(
                dry_run=args.dry_run, force=args.force,
                central_url=args.central, project=args.project,
                _print=lambda m: print(m, flush=True),
            )
        else:
            parser.print_help()
            sys.exit(1)

        # Exit with error code if there were conflicts or aborted operations
        if any("CONFLICT" in m or "aborted" in m for m in messages):
            sys.exit(1)

    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
