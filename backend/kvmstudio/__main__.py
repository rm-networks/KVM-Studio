from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, default_config_path, load_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kvm-studio", description="KVM Studio")
    parser.add_argument(
        "--mode",
        choices=["desktop", "web"],
        help="interface mode (default: [interface] mode from the configuration)",
    )
    parser.add_argument("--config", type=Path, help="configuration file to use")
    parser.add_argument(
        "--check", action="store_true", help="check the configuration and the host, then exit"
    )
    parser.add_argument(
        "--reload", action="store_true", help="web mode: restart on code changes (development)"
    )
    parser.add_argument(
        "--no-browser", action="store_true", help="web mode: do not open the browser"
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path: Path = args.config or default_config_path()
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2

    if args.check:
        from . import check

        return check.run(config, config_path)

    mode = args.mode or config.interface.mode
    if mode == "web":
        from .shell import web

        return web.run(
            config,
            args.config,
            open_browser=not args.no_browser and not args.reload,
            reload=args.reload,
        )

    if args.reload:
        print("--reload is only available with --mode web", file=sys.stderr)
        return 2
    from .shell import desktop

    return desktop.run(config)


if __name__ == "__main__":
    sys.exit(main())
