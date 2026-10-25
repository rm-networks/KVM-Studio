import { useCallback, useEffect, useState } from "react";

import { api, ApiError, type AppInfo, type LibraryInfo, type VmSummary } from "../api/client";
import { type ServerEvent, subscribeEvents } from "../api/events";
import { setViewers } from "../features/console/viewers";

export interface AppData {
  info: AppInfo | null;
  vms: VmSummary[] | null;
  /** Every VM name seen so far, kept when a VM drops out of the list for a moment. */
  knownNames: ReadonlyMap<string, string>;
  library: LibraryInfo | null;
  error: ApiError | null;
  loading: boolean;
  /** libvirt dropped and the backend is trying to reconnect. */
  libvirtLost: boolean;
  refresh: () => void;
}

function asApiError(err: unknown): ApiError {
  return err instanceof ApiError ? err : new ApiError(0, "http.error", String(err));
}

function applyEvent(vms: VmSummary[] | null, event: ServerEvent): VmSummary[] | null {
  if (vms === null) return vms;
  if (event.type === "vm.changed") {
    const index = vms.findIndex((vm) => vm.uuid === event.vm.uuid);
    if (index === -1) return [...vms, event.vm];
    return vms.map((vm, i) => (i === index ? event.vm : vm));
  }
  if (event.type === "vm.removed") return vms.filter((vm) => vm.uuid !== event.uuid);
  return vms;
}

export function useAppData(): AppData {
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [vms, setVms] = useState<VmSummary[] | null>(null);
  const [knownNames, setKnownNames] = useState<ReadonlyMap<string, string>>(new Map());
  const remember = useCallback((list: VmSummary[]) => {
    setKnownNames((names) => {
      if (list.every((vm) => names.get(vm.uuid) === vm.name)) return names;
      const next = new Map(names);
      for (const vm of list) next.set(vm.uuid, vm.name);
      return next;
    });
  }, []);
  const [library, setLibrary] = useState<LibraryInfo | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [libvirtLost, setLibvirtLost] = useState(false);
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.info(), api.listVms(), api.library()])
      .then(([nextInfo, nextVms, nextLibrary]) => {
        if (cancelled) return;
        setInfo(nextInfo);
        setVms(nextVms);
        remember(nextVms);
        setLibrary(nextLibrary);
        setError(null);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(asApiError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [generation, remember]);

  const refresh = useCallback(() => {
    setLoading(true);
    setGeneration((g) => g + 1);
  }, []);

  useEffect(
    () =>
      subscribeEvents({
        onEvent: (event) => {
          if (event.type === "console.viewers") {
            setViewers(event.uuid, event.count);
            return;
          }
          if (event.type === "library.changed") {
            refresh();
            return;
          }
          if (event.type === "connection") {
            setLibvirtLost(event.state === "lost");
            if (event.state === "restored") refresh();
            return;
          }
          if (event.type === "vm.changed") remember([event.vm]);
          setVms((current) => applyEvent(current, event));
        },
        onReconnect: refresh,
      }),
    [refresh, remember],
  );

  return { info, vms, knownNames, library, error, loading, libvirtLost, refresh };
}
