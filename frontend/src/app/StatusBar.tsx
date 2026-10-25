import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { AppInfo, VmSummary } from "../api/client";
import { useTasks } from "../components/taskTracker";
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
  const { tasks, cancel } = useTasks();
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
      {tasks.map(({ info, label, cancelling }) => {
        // No percentage when libvirt gives none (internal snapshots): a moving bar.
        const known = info.progress > 0;
        return (
          <span key={info.id} className="statusbar-task">
            <span>
              {cancelling
                ? t("tasks.cancelling", { label })
                : known
                  ? t("tasks.progress", { label, percent: Math.round(info.progress * 100) })
                  : label}
            </span>
            <span
              className={known ? "statusbar-meter" : "statusbar-meter statusbar-meter-busy"}
              role="progressbar"
              aria-label={label}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={known ? Math.round(info.progress * 100) : undefined}
            >
              <span style={known ? { width: `${info.progress * 100}%` } : undefined} />
            </span>
            <button
              type="button"
              className="icon-button statusbar-cancel"
              aria-label={t("tasks.cancel", { label })}
              title={t("tasks.cancel", { label })}
              disabled={cancelling}
              onClick={() => cancel(info.id)}
            >
              <X />
            </button>
          </span>
        );
      })}
      {vms && (
        <span>
          {t("status.vmCount", { count: vms.length })}, {t("status.running", { count: running })}
        </span>
      )}
    </footer>
  );
}
