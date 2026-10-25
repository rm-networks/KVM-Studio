import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { ChevronsRight, House, Monitor, X } from "lucide-react";
import { useRef } from "react";
import { useTranslation } from "react-i18next";

import { useOverflow } from "./useOverflow";
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

// Room kept for the overflow button.
const MORE_WIDTH = 36;

export function TabBar({ tabs, active, onActivate, onClose }: Props) {
  const { t } = useTranslation();
  const bar = useRef<HTMLDivElement>(null);
  const measure = useRef<HTMLDivElement>(null);
  const all = [{ id: HOME_TAB, label: t("home.tab") }, ...tabs];
  const fit = useOverflow(bar, measure, all.length, MORE_WIDTH);

  // The active tab always stays in view, in place of the last one that fits.
  let shown = all.slice(0, fit);
  const activeTab = all.find((tab) => tab.id === active);
  if (activeTab && !shown.includes(activeTab)) shown = [...shown.slice(0, -1), activeTab];
  const hidden = all.filter((tab) => !shown.includes(tab));

  const icon = (id: string) => (id === HOME_TAB ? <House aria-hidden /> : <Monitor aria-hidden />);

  return (
    <div className="tabbar">
      <div className="tabbar-tabs" role="tablist" ref={bar}>
        {shown.map((tab) => (
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
            {icon(tab.id)}
            <span className="tab-label">{tab.label}</span>
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
                <X />
              </button>
            )}
          </div>
        ))}
      </div>
      {hidden.length > 0 && (
        <DropdownMenu.Root>
          <DropdownMenu.Trigger
            className="icon-button tabbar-more"
            title={t("tabs.more")}
            aria-label={t("tabs.more")}
          >
            <ChevronsRight />
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content className="menu" align="end" sideOffset={2}>
              {hidden.map((tab) => (
                <DropdownMenu.Item
                  key={tab.id}
                  className="menu-item"
                  onSelect={() => onActivate(tab.id)}
                >
                  <span className="menu-indicator">{icon(tab.id)}</span>
                  <span className="menu-label">{tab.label}</span>
                </DropdownMenu.Item>
              ))}
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      )}
      {/* Copy of every tab, never shown, to know their widths. */}
      <div className="tabbar-measure" aria-hidden ref={measure}>
        {all.map((tab) => (
          <div key={tab.id} className="tab">
            {icon(tab.id)}
            <span className="tab-label">{tab.label}</span>
            {tab.id !== HOME_TAB && (
              <span className="tab-close">
                <X />
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
