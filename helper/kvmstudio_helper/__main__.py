from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import DEFAULT_PATH, ConfigError, load
from .errors import HelperError
from .ops.iso_library import clear
from .server import HelperServer, run_tool


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kvmstudio-helper")
    parser.add_argument("--config", type=Path, default=DEFAULT_PATH)
    parser.add_argument(
        "--clear-state",
        action="store_true",
        help="remove the ACL entries the helper added, forget the declared libraries, then exit",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        config = load(args.config)
    except ConfigError as exc:
        print(f"kvmstudio-helper: {exc}", file=sys.stderr)
        return 1
    if args.clear_state:
        # Package removal: runs as root from the maintainer script.
        try:
            clear(config, run_tool, remove_acls=True)
        except HelperError as exc:
            print(f"kvmstudio-helper: {exc}", file=sys.stderr)
            return 1
        config.state.unlink(missing_ok=True)
        return 0
    with HelperServer(config) as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
