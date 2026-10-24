import { useCallback, useEffect, useState } from "react";

import { api, type CdromDevice, type VmSummary } from "../../api/client";

/** CD/DVD drives of the VM, refreshed when it changes state. */
export function useCdroms(vm: VmSummary | null): { drives: CdromDevice[]; reload: () => void } {
  const [drives, setDrives] = useState<CdromDevice[]>([]);
  const [generation, setGeneration] = useState(0);
  const uuid = vm?.uuid;
  const state = vm?.state;

  useEffect(() => {
    if (!uuid) return;
    let cancelled = false;
    api
      .cdroms(uuid)
      .then((list) => !cancelled && setDrives(list))
      .catch(() => !cancelled && setDrives([]));
    return () => {
      cancelled = true;
    };
  }, [uuid, state, generation]);

  const reload = useCallback(() => setGeneration((g) => g + 1), []);
  return { drives: uuid ? drives : [], reload };
}
