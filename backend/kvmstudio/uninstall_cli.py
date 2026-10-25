"""`kvm-studio --uninstall`: the uninstall assistant's questions, in a terminal."""

from __future__ import annotations

from collections.abc import Callable

from . import helper_client
from .config import Config
from .errors import ApiException
from .i18n import t
from .libvirt_conn import LibvirtConnection
from .services import uninstall

YES = {"y", "yes", "o", "oui"}


def _yes(ask: Callable[[str], str], question: str) -> bool:
    return ask(f"{question} {t('cli.yes_no')} ").strip().lower() in YES


def _action(delete: bool) -> str:
    return t("uninstall.delete" if delete else "uninstall.keep")


def run(
    config: Config,
    *,
    ask: Callable[[str], str] = input,
    out: Callable[[str], None] = print,
) -> int:
    conn = LibvirtConnection(config.libvirt.uri)
    try:
        return _run(conn, config, ask, out)
    except (EOFError, KeyboardInterrupt):
        out("\n" + t("cli.cancelled"))
        return 1
    except ApiException as exc:
        out(t("cli.error", error=exc))
        return 1
    finally:
        conn.close()


def _run(
    conn: LibvirtConnection,
    config: Config,
    ask: Callable[[str], str],
    out: Callable[[str], None],
) -> int:
    plan = uninstall.plan(conn, config)
    out(t("uninstall.title") + "\n")

    delete_vms = False
    if plan.vms:
        out(t("uninstall.vms"))
        for vm in plan.vms:
            out(f"  {vm.name}")
            for path in vm.delete:
                out(f"    {path}")
        for path in plan.extra_files:
            out("  " + t("uninstall.other_file", path=path))
        if plan.keep or any(vm.keep for vm in plan.vms):
            out(t("uninstall.always_kept"))
        if plan.kept_vms:
            out(t("uninstall.foreign_vms", names=", ".join(plan.kept_vms)))
        if _yes(ask, t("uninstall.ask_vms")):
            if plan.running:
                out(t("uninstall.power_off", names=", ".join(plan.running)))
                return 1
            delete_vms = _yes(ask, t("uninstall.ask_vms_again"))
    else:
        out(t("uninstall.no_vms"))

    delete_networks = False
    if plan.networks:
        out("\n" + t("uninstall.networks"))
        for n in plan.networks:
            note = (
                " " + t("uninstall.network_kept", names=", ".join(n.used_by_kept))
                if n.used_by_kept
                else ""
            )
            out(f"  {n.name} ({n.bridge}){note}")
        delete_networks = _yes(ask, t("uninstall.ask_networks"))

    delete_settings = False
    if plan.settings:
        out("\n" + t("uninstall.settings"))
        for path in plan.settings:
            out(f"  {path}")
        delete_settings = _yes(ask, t("uninstall.ask_settings"))

    out("\n" + t("uninstall.summary"))
    out("  " + t("uninstall.summary_vms", action=_action(delete_vms)))
    out("  " + t("uninstall.summary_networks", action=_action(delete_networks)))
    out("  " + t("uninstall.summary_settings", action=_action(delete_settings)))
    packaged = uninstall.installed_from_package()
    package = t(
        "uninstall.summary_package_remove" if packaged else "uninstall.summary_package_none"
    )
    out("  " + package)
    if not _yes(ask, t("uninstall.ask_go")):
        out(t("cli.cancelled"))
        return 1

    choices = uninstall.Choices(delete_vms, delete_networks, delete_settings)
    report = uninstall.execute(conn, config, choices, plan.plan_id)
    if report.deleted_vms:
        out(t("uninstall.deleted_vms", names=", ".join(report.deleted_vms)))
    for path in report.failed_files:
        out(t("uninstall.not_deleted", path=path))
    if report.deleted_networks:
        out(t("uninstall.deleted_networks", names=", ".join(report.deleted_networks)))
    if report.kept_networks:
        out(t("uninstall.kept_networks", names=", ".join(report.kept_networks)))
    if packaged:
        try:
            helper_client.call("remove_package", {})
        except ApiException as exc:
            out(t("uninstall.package_failed", error=exc))
            return 1
        out(t("uninstall.package_removing"))
    out(t("uninstall.done"))
    return 0
