"""Command-line interface for tlc-shared-docs."""

from __future__ import annotations

import argparse
import sys

from tlc_shared_docs import __version__
from tlc_shared_docs.core import get_files, push_files


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tlc-shared-docs",
        description="Share documentation files between Git repositories.",
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
        if args.command == "get":
            messages = get_files(
                dry_run=args.dry_run, central_url=args.central, project=args.project,
            )
        elif args.command == "push":
            messages = push_files(
                dry_run=args.dry_run, force=args.force,
                central_url=args.central, project=args.project,
            )
        else:
            parser.print_help()
            sys.exit(1)

        for msg in messages:
            print(msg)

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
