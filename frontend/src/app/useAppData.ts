import { useCallback, useEffect, useState } from "react";

import { api, ApiError, type AppInfo, type VmSummary } from "../api/client";

export interface AppData {
  info: AppInfo | null;
  vms: VmSummary[] | null;
  error: ApiError | null;
  loading: boolean;
  refresh: () => void;
}

function asApiError(err: unknown): ApiError {
  return err instanceof ApiError ? err : new ApiError(0, "http.error", String(err));
}

export function useAppData(): AppData {
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [vms, setVms] = useState<VmSummary[] | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [generation, setGeneration] = useState(0);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.info(), api.listVms()])
      .then(([nextInfo, nextVms]) => {
        if (cancelled) return;
        setInfo(nextInfo);
        setVms(nextVms);
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
  }, [generation]);

  const refresh = useCallback(() => {
    setLoading(true);
    setGeneration((g) => g + 1);
  }, []);

  return { info, vms, error, loading, refresh };
}
