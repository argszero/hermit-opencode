"""`hermit-opencode <adapter> --output <dir>`: write an OpenCode configuration."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .emit import Unsupported, build
from .manifest import AdapterError


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hermit-opencode",
        description="Convert a hermit adapter into an OpenCode configuration: opencode.json, "
                    ".opencode/context.md, .opencode/skills/ and .opencode/agents/, with the adapter embedded.")
    p.add_argument("adapter", type=Path, help="the adapter directory (either manifest layout)")
    p.add_argument("--output", type=Path, required=True, help="where to write the configuration")
    p.add_argument("--allow-lossy", action="store_true",
                   help="leave out the parts OpenCode cannot carry instead of failing; listed under `omitted`")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = build(args.adapter, args.output, allow_lossy=args.allow_lossy)
    except (Unsupported, AdapterError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
