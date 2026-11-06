"""`hermit-opencode convert <adapter> --output <dir>`, `hermit-opencode deploy <adapter> --workspace <dir>`."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .deploy import deploy
from .emit import build
from .manifest import AdapterError

COMMANDS = ("convert", "deploy")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hermit-opencode",
        description="Bring a hermit adapter to OpenCode. `convert` writes opencode.json, .opencode/context.md, "
                    ".opencode/skills/ and .opencode/agents/ into a directory of its own, with the adapter "
                    "embedded; `deploy` writes the same parts into an existing workspace, in place.")
    sub = p.add_subparsers(dest="command", metavar="{convert,deploy}")

    con = sub.add_parser("convert", help="write an OpenCode configuration into a fresh output directory")
    con.add_argument("adapter", type=Path, help="the adapter directory (either manifest layout)")
    con.add_argument("--output", type=Path, required=True, help="where to write the configuration")
    con.add_argument("--allow-lossy", action="store_true",
                     help="leave out the parts OpenCode cannot carry instead of failing; listed under `omitted`")

    dep = sub.add_parser("deploy", help="write the configuration into an existing workspace, in place")
    dep.add_argument("adapter", type=Path, help="the adapter directory (either manifest layout)")
    dep.add_argument("--workspace", type=Path, required=True, help="the project OpenCode will be opened in")
    dep.add_argument("--allow-lossy", action="store_true",
                     help="leave out the parts OpenCode cannot carry instead of failing; listed under `omitted`")
    dep.add_argument("--force", action="store_true",
                     help="adopt a nonempty workspace this tool did not create, reporting what that overwrites")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # 0.1.x spelled its only command as `hermit-opencode <adapter> --output <dir>`, and
    # that spelling is still the first command in the README, so it keeps working.
    if argv and argv[0] not in COMMANDS and argv[0] not in ("-h", "--help"):
        argv = ["convert", *argv]
    args = parser().parse_args(argv)
    try:
        if args.command == "deploy":
            result = deploy(args.adapter, args.workspace, allow_lossy=args.allow_lossy, force=args.force)
        else:
            result = build(args.adapter, args.output, allow_lossy=args.allow_lossy)
    except (AdapterError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
