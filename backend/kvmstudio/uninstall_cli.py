"""`kvm-studio --uninstall`: the uninstall assistant's questions, in a terminal."""

from __future__ import annotations

from collections.abc import Callable

from . import helper_client
from .config import Config
from .errors import ApiException
from .libvirt_conn import LibvirtConnection
from .services import uninstall

YES = {"y", "yes", "o", "oui"}


def _yes(ask: Callable[[str], str], question: str) -> bool:
    return ask(f"{question} [y/N] ").strip().lower() in YES


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
        out("\nCancelled, nothing was changed.")
        return 1
    except ApiException as exc:
        out(f"Error: {exc}")
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
    out("Uninstall KVM Studio\n")

    delete_vms = False
    if plan.vms:
        out("Virtual machines created by KVM Studio, and the files that would be deleted:")
        for vm in plan.vms:
            out(f"  {vm.name}")
            for path in vm.delete:
                out(f"    {path}")
        for path in plan.extra_files:
            out(f"  (other file) {path}")
        if plan.keep or any(vm.keep for vm in plan.vms):
            out("Always kept: ISO images, files used by other VMs, files outside the library.")
        if plan.kept_vms:
            out(f"VMs created outside KVM Studio, always kept: {', '.join(plan.kept_vms)}")
        if _yes(ask, "Delete these virtual machines and files?"):
            if plan.running:
                out(f"Power these VMs off first: {', '.join(plan.running)}")
                return 1
            delete_vms = _yes(ask, "This cannot be undone. Really delete them?")
    else:
        out("No virtual machine created by KVM Studio.")

    delete_networks = False
    if plan.networks:
        out("\nkvmnet networks:")
        for n in plan.networks:
            note = f" (kept, used by {', '.join(n.used_by_kept)})" if n.used_by_kept else ""
            out(f"  {n.name} ({n.bridge}){note}")
        delete_networks = _yes(ask, "Delete the networks no remaining VM uses?")

    delete_settings = False
    if plan.settings:
        out("\nSettings:")
        for path in plan.settings:
            out(f"  {path}")
        delete_settings = _yes(ask, "Delete your settings?")

    out("\nSummary:")
    out(f"  virtual machines: {'delete' if delete_vms else 'keep'}")
    out(f"  networks: {'delete' if delete_networks else 'keep'}")
    out(f"  settings: {'delete' if delete_settings else 'keep'}")
    packaged = uninstall.installed_from_package()
    out(f"  package: {'remove' if packaged else 'none (running from the sources)'}")
    if not _yes(ask, "Go ahead?"):
        out("Cancelled, nothing was changed.")
        return 1

    choices = uninstall.Choices(delete_vms, delete_networks, delete_settings)
    report = uninstall.execute(conn, config, choices, plan.plan_id)
    if report.deleted_vms:
        out(f"Deleted VMs: {', '.join(report.deleted_vms)}")
    for path in report.failed_files:
        out(f"Could not delete {path}")
    if report.deleted_networks:
        out(f"Deleted networks: {', '.join(report.deleted_networks)}")
    if report.kept_networks:
        out(f"Kept networks: {', '.join(report.kept_networks)}")
    if packaged:
        try:
            helper_client.call("remove_package", {})
        except ApiException as exc:
            out(f"The package could not be removed ({exc}). Run: sudo dnf remove kvm-studio")
            return 1
        out("Removing the package (follow it with: journalctl -u kvm-studio-removal).")
    out("Done.")
    return 0
