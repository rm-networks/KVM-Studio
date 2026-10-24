import { useTranslation } from "react-i18next";

import type { AppInfo, VmSummary } from "../api/client";
import type { ConsoleHandle } from "../features/console/consoleRegistry";
import "./StatusBar.css";

interface Props {
  info: AppInfo | null;
  vms: VmSummary[] | null;
  libvirtLost: boolean;
  vmConsole: ConsoleHandle | null;
}

export function StatusBar({ info, vms, libvirtLost, vmConsole }: Props) {
  const { t } = useTranslation();
  const running = vms?.filter((vm) => vm.state === "running").length ?? 0;

  return (
    <footer className="statusbar">
      <span
        className={
          libvirtLost
            ? "statusbar-dot statusbar-dot-lost"
            : info
              ? "statusbar-dot"
              : "statusbar-dot statusbar-dot-off"
        }
      />
      <span>
        {libvirtLost
          ? t("status.lost")
          : info
            ? t("status.connected", { uri: info.libvirt.uri })
            : t("status.disconnected")}
      </span>
      {info && (
        <span className="statusbar-muted">
          {t("status.versions", {
            libvirt: info.libvirt.libvirt_version,
            driver: info.libvirt.driver,
            hypervisor: info.libvirt.hypervisor_version,
          })}
        </span>
      )}
      <span className="statusbar-spacer" />
      {vmConsole && (
        <span className={vmConsole.grabbed ? "statusbar-grab active" : "statusbar-grab"}>
          {vmConsole.grabbed ? t("status.release") : t("status.grabHint")}
        </span>
      )}
      {vms && (
        <span>
          {t("status.vmCount", { count: vms.length })}, {t("status.running", { count: running })}
        </span>
      )}
    </footer>
  );
}
