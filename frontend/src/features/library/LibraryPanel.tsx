import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Check, ListFilter, RefreshCw, Search, X } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import type { ApiError, VmSummary } from "../../api/client";
import { ErrorMessage } from "../../components/ErrorMessage";
import { type VmFilter, type VmSort, visibleVms } from "./filter";
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

function RadioItem({ value, label }: { value: string; label: string }) {
  return (
    <DropdownMenu.RadioItem className="menu-item" value={value}>
      <span className="menu-indicator">
        <DropdownMenu.ItemIndicator>
          <Check size={13} />
        </DropdownMenu.ItemIndicator>
      </span>
      <span className="menu-label">{label}</span>
    </DropdownMenu.RadioItem>
  );
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
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<VmFilter>("all");
  const [sort, setSort] = useState<VmSort>("name");
  const shown = useMemo(
    () => (vms ? visibleVms(vms, query, filter, sort) : null),
    [vms, query, filter, sort],
  );
  const narrowed = query.trim() !== "" || filter !== "all";

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
      <div className="library-search">
        <Search size={13} className="library-search-icon" aria-hidden />
        <input
          type="search"
          value={query}
          placeholder={t("library.search")}
          aria-label={t("library.search")}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setQuery("");
          }}
        />
        <DropdownMenu.Root>
          <DropdownMenu.Trigger
            className={filter !== "all" ? "library-button active" : "library-button"}
            title={t("library.filter")}
            aria-label={t("library.filter")}
          >
            <ListFilter size={13} />
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content className="menu" align="end" sideOffset={2}>
              <DropdownMenu.Label className="menu-group-label">
                {t("library.show")}
              </DropdownMenu.Label>
              <DropdownMenu.RadioGroup
                value={filter}
                onValueChange={(v) => setFilter(v as VmFilter)}
              >
                <RadioItem value="all" label={t("library.allVms")} />
                <RadioItem value="running" label={t("library.runningVms")} />
              </DropdownMenu.RadioGroup>
              <DropdownMenu.Separator className="menu-separator" />
              <DropdownMenu.Label className="menu-group-label">
                {t("library.sortBy")}
              </DropdownMenu.Label>
              <DropdownMenu.RadioGroup value={sort} onValueChange={(v) => setSort(v as VmSort)}>
                <RadioItem value="name" label={t("library.sortName")} />
                <RadioItem value="state" label={t("library.sortState")} />
              </DropdownMenu.RadioGroup>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
      <div className="library-content">
        {error && <ErrorMessage error={error} onRetry={onRefresh} />}
        {!error && shown === null && <p className="library-note">{t("library.loading")}</p>}
        {shown !== null && (
          <LibraryTree
            vms={shown}
            selected={selected}
            onSelect={onSelect}
            onOpen={onOpen}
            emptyLabel={narrowed ? t("library.noMatch") : undefined}
          />
        )}
      </div>
    </aside>
  );
}
