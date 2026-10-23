import { useTranslation } from "react-i18next";

import type { VmState } from "../../api/client";

const visibleStates: ReadonlySet<VmState> = new Set(["running", "paused", "suspended", "crashed"]);

export function StateDot({ state }: { state: VmState }) {
  const { t } = useTranslation();
  if (!visibleStates.has(state)) return null;
  return (
    <span className={`state-dot state-${state}`} role="img" aria-label={t(`state.${state}`)} />
  );
}
