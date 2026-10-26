"""The command line: options, then the check, the uninstaller or one of the two modes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import APP_NAME, __version__
from .config import ConfigError, default_config_path, load_config
from .i18n import set_language, t


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kvm-studio", description=APP_NAME)
    parser.add_argument(
        "--mode",
        choices=["desktop", "web"],
        help=t("cli.help_mode"),
    )
    parser.add_argument("--config", type=Path, help=t("cli.help_config"))
    parser.add_argument("--check", action="store_true", help=t("cli.help_check"))
    parser.add_argument("--reload", action="store_true", help=t("cli.help_reload"))
    parser.add_argument("--no-browser", action="store_true", help=t("cli.help_no_browser"))
    parser.add_argument("--uninstall", action="store_true", help=t("cli.help_uninstall"))
    parser.add_argument(
        "--uninstall-wizard", action="store_true", help=t("cli.help_uninstall_wizard")
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
    set_language(config.ui.language)

    if args.check:
        from . import check

        return check.run(config, config_path)

    if args.uninstall:
        from . import uninstall_cli

        return uninstall_cli.run(config)

    if args.uninstall_wizard:
        from .shell import desktop

        return desktop.run(config, args.config, page="uninstall")

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
        print(t("cli.reload_web_only"), file=sys.stderr)
        return 2
    from .shell import desktop

    return desktop.run(config, args.config)
