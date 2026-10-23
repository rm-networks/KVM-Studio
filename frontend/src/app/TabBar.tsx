import { House, Monitor, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import "./TabBar.css";

export const HOME_TAB = "home";

export interface TabInfo {
  id: string;
  label: string;
}

interface Props {
  tabs: TabInfo[];
  active: string;
  onActivate: (id: string) => void;
  onClose: (id: string) => void;
}

export function TabBar({ tabs, active, onActivate, onClose }: Props) {
  const { t } = useTranslation();
  const all = [{ id: HOME_TAB, label: t("home.tab") }, ...tabs];

  return (
    <div className="tabbar" role="tablist">
      {all.map((tab) => (
        <div
          key={tab.id}
          className="tab"
          role="tab"
          aria-selected={tab.id === active}
          tabIndex={tab.id === active ? 0 : -1}
          onClick={() => onActivate(tab.id)}
          onAuxClick={(e) => {
            if (e.button === 1 && tab.id !== HOME_TAB) onClose(tab.id);
          }}
        >
          {tab.id === HOME_TAB ? (
            <House size={13} aria-hidden />
          ) : (
            <Monitor size={13} strokeWidth={1.75} aria-hidden />
          )}
          <span>{tab.label}</span>
          {tab.id !== HOME_TAB && (
            <button
              type="button"
              className="tab-close"
              aria-label={t("tabs.close")}
              title={t("tabs.close")}
              onClick={(e) => {
                e.stopPropagation();
                onClose(tab.id);
              }}
            >
              <X size={12} />
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
