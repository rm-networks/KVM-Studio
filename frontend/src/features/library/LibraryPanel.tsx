import { RefreshCw, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ApiError, VmSummary } from "../../api/client";
import { ErrorMessage } from "../../components/ErrorMessage";
import { LibraryTree } from "./LibraryTree";
import "./LibraryPanel.css";

interface Props {
  vms: VmSummary[] | null;
  loading: boolean;
  error: ApiError | null;
  selected: string | null;
  onSelect: (id: string) => void;
  onOpen: (uuid: string) => void;
  onRefresh: () => void;
  onClose: () => void;
}

export function LibraryPanel({
  vms,
  loading,
  error,
  selected,
  onSelect,
  onOpen,
  onRefresh,
  onClose,
}: Props) {
  const { t } = useTranslation();

  return (
    <aside className="library" aria-label={t("library.title")}>
      <div className="library-header">
        <span className="library-title">{t("library.title")}</span>
        <button
          type="button"
          className="library-button"
          title={t("library.refresh")}
          aria-label={t("library.refresh")}
          onClick={onRefresh}
          disabled={loading}
        >
          <RefreshCw size={13} className={loading ? "spin" : undefined} />
        </button>
        <button
          type="button"
          className="library-button"
          title={t("library.close")}
          aria-label={t("library.close")}
          onClick={onClose}
        >
          <X size={14} />
        </button>
      </div>
      <div className="library-content">
        {error && <ErrorMessage error={error} onRetry={onRefresh} />}
        {!error && vms === null && <p className="library-note">{t("library.loading")}</p>}
        {vms !== null && (
          <LibraryTree vms={vms} selected={selected} onSelect={onSelect} onOpen={onOpen} />
        )}
      </div>
    </aside>
  );
}
