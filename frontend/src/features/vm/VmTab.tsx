import { Cpu, Link2, MemoryStick, Play, Settings2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type VmSummary } from "../../api/client";
import { VmConsole } from "../console/VmConsole";
import { powerAllowed } from "./power";
import { useVmActions } from "./vmActionsContext";
import "./VmTab.css";

const LIVE_STATES: ReadonlySet<VmSummary["state"]> = new Set(["running", "paused"]);

/** VMs whose disks are overlays of this one's: they break if it runs. */
function useLinkedClones(uuid: string | undefined, state: string | undefined): string[] {
  const [names, setNames] = useState<string[]>([]);
  useEffect(() => {
    if (!uuid) return;
    let cancelled = false;
    api
      .linkedClones(uuid)
      .then((r) => !cancelled && setNames(r.names))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [uuid, state]);
  return names;
}

export function VmTab({ vm, onSettings }: { vm: VmSummary | undefined; onSettings: () => void }) {
  const { t } = useTranslation();
  const actions = useVmActions();
  const clones = useLinkedClones(vm?.uuid, vm?.state);
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
          <Play />
          {t("summary.start")}
        </button>
      )}
      <button type="button" className="vm-summary-action" onClick={onSettings}>
        <Settings2 />
        {t("summary.settings")}
      </button>
      <h2 className="vm-summary-heading">{t("summary.devices")}</h2>
      <table className="vm-summary-devices">
        <tbody>
          <tr>
            <td>
              <span className="vm-summary-device">
                <MemoryStick aria-hidden />
                {t("summary.memory")}
              </span>
            </td>
            <td>
              {vm.memory_mib >= 1024 && vm.memory_mib % 1024 === 0
                ? t("units.gib", { value: vm.memory_mib / 1024 })
                : t("units.mib", { value: vm.memory_mib })}
            </td>
          </tr>
          <tr>
            <td>
              <span className="vm-summary-device">
                <Cpu aria-hidden />
                {t("summary.processors")}
              </span>
            </td>
            <td>{vm.vcpus}</td>
          </tr>
          {clones.length > 0 && (
            <tr>
              <td>
                <span className="vm-summary-device">
                  <Link2 aria-hidden />
                  {t("clone.linkedClones")}
                </span>
              </td>
              <td>{clones.join(", ")}</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
