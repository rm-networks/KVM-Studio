import { Cpu, MemoryStick, Play, Settings2 } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { VmSummary } from "../../api/client";
import { VmConsole } from "../console/VmConsole";
import { powerAllowed } from "./power";
import { useVmActions } from "./vmActionsContext";
import "./VmTab.css";

const LIVE_STATES: ReadonlySet<VmSummary["state"]> = new Set(["running", "paused"]);

export function VmTab({ vm, onSettings }: { vm: VmSummary | undefined; onSettings: () => void }) {
  const { t } = useTranslation();
  const actions = useVmActions();
  if (!vm) return <div className="vm-tab-note">{t("errors.libvirt.no_domain")}</div>;
  if (LIVE_STATES.has(vm.state)) return <VmConsole uuid={vm.uuid} />;

  return (
    <div className="vm-summary">
      <h1 className="vm-summary-name">{vm.name}</h1>
      <p className="vm-summary-state">{t(`state.${vm.state}`)}</p>
      {powerAllowed(vm.state, "start") && (
        <button
          type="button"
          className="vm-summary-action"
          onClick={() => actions.power(vm, "start")}
        >
          <Play size={14} />
          {t("summary.start")}
        </button>
      )}
      <button type="button" className="vm-summary-action" onClick={onSettings}>
        <Settings2 size={14} />
        {t("summary.settings")}
      </button>
      <h2 className="vm-summary-heading">{t("summary.devices")}</h2>
      <table className="vm-summary-devices">
        <tbody>
          <tr>
            <td>
              <MemoryStick size={14} aria-hidden />
              {t("summary.memory")}
            </td>
            <td>
              {vm.memory_mib >= 1024 && vm.memory_mib % 1024 === 0
                ? t("units.gib", { value: vm.memory_mib / 1024 })
                : t("units.mib", { value: vm.memory_mib })}
            </td>
          </tr>
          <tr>
            <td>
              <Cpu size={14} aria-hidden />
              {t("summary.processors")}
            </td>
            <td>{vm.vcpus}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}
