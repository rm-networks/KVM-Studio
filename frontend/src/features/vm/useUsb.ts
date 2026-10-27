import { useCallback, useEffect, useState } from "react";

import { api, type UsbDevice, type VmSummary } from "../../api/client";

/**
 * USB storage devices of the host, refreshed when the VM changes state and
 * when the VM menu opens. A LAN guest gets none: the host is not theirs.
 */
export function useUsb(vm: VmSummary | null): { devices: UsbDevice[]; reload: () => void } {
  const [devices, setDevices] = useState<UsbDevice[]>([]);
  const [generation, setGeneration] = useState(0);
  const uuid = vm?.uuid;
  const state = vm?.state;

  useEffect(() => {
    if (!uuid) return;
    let cancelled = false;
    api
      .usbDevices()
      .then((list) => !cancelled && setDevices(list))
      .catch(() => !cancelled && setDevices([]));
    return () => {
      cancelled = true;
    };
  }, [uuid, state, generation]);

  const reload = useCallback(() => setGeneration((g) => g + 1), []);
  return { devices: uuid ? devices : [], reload };
}
