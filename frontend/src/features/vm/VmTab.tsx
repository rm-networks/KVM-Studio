import { Power } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { VmSummary } from "../../api/client";
import { VmConsole } from "../console/VmConsole";
import "./VmTab.css";

const LIVE_STATES: ReadonlySet<VmSummary["state"]> = new Set(["running", "paused"]);

export function VmTab({ vm }: { vm: VmSummary | undefined }) {
  const { t } = useTranslation();
  if (!vm) return <div className="vm-tab-note">{t("errors.libvirt.no_domain")}</div>;
  if (LIVE_STATES.has(vm.state)) return <VmConsole uuid={vm.uuid} />;
  return (
    <div className="vm-tab-note">
      <Power size={28} strokeWidth={1.25} aria-hidden />
      <span>{t("console.poweredOff")}</span>
    </div>
  );
}
