from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import DEFAULT_PATH, ConfigError, load
from .server import HelperServer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kvmstudio-helper")
    parser.add_argument("--config", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        config = load(args.config)
    except ConfigError as exc:
        print(f"kvmstudio-helper: {exc}", file=sys.stderr)
        return 1
    with HelperServer(config) as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
