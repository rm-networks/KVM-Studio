from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import DEFAULT_PATH, ConfigError, load
from .errors import HelperError
from .ops import port_forward
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
    parser.add_argument(
        "--apply-forwards",
        nargs="*",
        metavar="HOOK_ARG",
        help="write the port forwarding table again from the state (libvirt network hook)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        config = load(args.config)
    except ConfigError as exc:
        print(f"kvmstudio-helper: {exc}", file=sys.stderr)
        return 1
    if args.apply_forwards is not None:
        # libvirt network hook: "<network> <operation> ..." (nothing to do but on start).
        if len(args.apply_forwards) < 2 or args.apply_forwards[1] == "started":
            try:
                port_forward.apply(config, run_tool)
            except HelperError as exc:
                print(f"kvmstudio-helper: {exc}", file=sys.stderr)
                return 1
        return 0
    if args.clear_state:
        # Package removal: runs as root from the maintainer script.
        try:
            clear(config, run_tool, remove_acls=True)
            port_forward.clear(config, run_tool)
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
