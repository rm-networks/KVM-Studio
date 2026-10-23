import { createContext, useContext } from "react";

import type { PowerAction, VmSummary } from "../../api/client";

export interface VmActions {
  power: (vm: VmSummary, action: PowerAction) => void;
  rename: (vm: VmSummary) => void;
  remove: (vm: VmSummary, deleteFiles: boolean) => void;
}

export const VmActionsContext = createContext<VmActions | null>(null);

export function useVmActions(): VmActions {
  const actions = useContext(VmActionsContext);
  if (!actions) throw new Error("useVmActions outside VmActionsProvider");
  return actions;
}
