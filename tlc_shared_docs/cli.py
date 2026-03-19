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
        --clean                Remove local files no longer in the share list
        --central URL          Fetch config from a central repo URL
        -p, --project NAME     Project name, space-separated list, or 'all'

  push  Push local shared files to the remote repo
        --dry-run              Preview without making changes
        --force                Overwrite even if remote files changed
        -v, --verbose          Show detailed debug output for push
        --central URL          Fetch config from a central repo URL
        -p, --project NAME     Select a named project (multi-project configs)

  list  List available projects defined in shared.json

  branch Switch the source branch for a project (sprint workflows)
        BRANCH                 Branch name to switch to
        -p, --project NAME     Only update this project (default: all)

  init  Install a Claude agent skill file into this repo
        --skill NAME           Skill to install (player1=arch repo, player2=consumer)

examples:
  tlc-shared-docs list                           Show available projects
  tlc-shared-docs get -p agent-coder             Pull docs for a specific project
  tlc-shared-docs get -p all                    Pull docs for every project
  tlc-shared-docs get -p "agent-coder auth"      Pull docs for two projects
  tlc-shared-docs get --dry-run                  Preview what would be fetched
  tlc-shared-docs push --force                   Push and overwrite remote changes
  tlc-shared-docs push -p auth --dry-run         Preview push for a project
  tlc-shared-docs branch tag-code-mvp            Switch all projects to sprint branch
  tlc-shared-docs branch main -p agent-coder     Switch one project back to main
  tlc-shared-docs init --skill player1           Install Claude skill for arch repos
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
        help="Project name, space-separated list of names, or 'all'",
    )
    get_parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove local files no longer in the shared_files list",
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
    push_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed debug output for diagnosing push issues",
    )

    # --- list: show available projects ---
    sub.add_parser("list", help="List available projects in shared.json")

    # --- branch: switch the source branch ---
    branch_parser = sub.add_parser(
        "branch", help="Switch the source branch for get/push operations",
    )
    branch_parser.add_argument(
        "branch_name",
        metavar="BRANCH",
        help="Branch name to switch to (e.g. tag-code-mvp, main)",
    )
    branch_parser.add_argument(
        "-p", "--project",
        default=None,
        help="Only update this project (default: update all projects)",
    )

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


def _resolve_project_list(project_arg: str | None, root: Path) -> list[str | None]:
    """Expand a -p argument into a list of project names to process.

    - ``None``  → ``[None]``  (use default_project or single-source)
    - ``"all"`` → all project names from shared.json
    - ``"a b"`` → ``["a", "b"]``  (space-separated)
    - ``"a"``   → ``["a"]``
    """
    if project_arg is None:
        return [None]
    if project_arg.strip().lower() == "all":
        projects = cfg.list_projects(root)
        if not projects:
            return [None]  # legacy single-source — no named projects
        # strip " (default)" marker that list_projects appends
        return [p["name"].replace(" (default)", "") for p in projects]
    return project_arg.split()


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
        elif args.command == "branch":
            root = cfg.find_project_root()
            msgs = cfg.set_branch(root, args.branch_name, project=args.project)
            for m in msgs:
                print(m)
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
            root = cfg.find_project_root()
            project_list = _resolve_project_list(args.project, root)
            messages: list[str] = []
            for i, project in enumerate(project_list):
                if len(project_list) > 1:
                    header = f"\n--- {project or 'default'} ---"
                    print(header, flush=True)
                    messages.append(header)
                proj_msgs = get_files(
                    project_root=root,
                    dry_run=args.dry_run, central_url=args.central,
                    project=project, clean=args.clean,
                    _print=lambda m: print(m, flush=True),
                )
                messages.extend(proj_msgs)
        elif args.command == "push":
            messages = push_files(
                dry_run=args.dry_run, force=args.force,
                central_url=args.central, project=args.project,
                verbose=args.verbose,
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
