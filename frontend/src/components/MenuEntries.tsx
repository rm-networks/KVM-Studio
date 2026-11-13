import * as ContextMenu from "@radix-ui/react-context-menu";
import * as Menubar from "@radix-ui/react-menubar";
import { Check, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { MenuEntry } from "./menuModel";

interface Props {
  entries: MenuEntry[];
  /** Which Radix menu holds the entries: the menu bar or a context menu. */
  kind: "menubar" | "context";
}

/** The same entries, drawn the same way, in the menu bar and in context menus. */
export function MenuEntries({ entries, kind }: Props) {
  const { t } = useTranslation();
  // Both wrap the same menu primitives with the same parts; only the scope differs.
  const M = (kind === "menubar" ? Menubar : ContextMenu) as typeof Menubar;
  const formatKeys = (keys: string[]) =>
    keys.map((k) => t(`keys.${k}`, { defaultValue: k })).join("+");

  const render = (list: MenuEntry[]) =>
    list.map((entry, i) => {
      switch (entry.kind) {
        case "sep":
          return <M.Separator key={i} className="menu-separator" />;
        case "item":
          return (
            <M.Item
              key={i}
              className="menu-item"
              disabled={!entry.onSelect}
              onSelect={entry.onSelect}
            >
              <span className="menu-indicator" />
              <span className="menu-label">{entry.label}</span>
              {entry.keys && <span className="menu-keys">{formatKeys(entry.keys)}</span>}
            </M.Item>
          );
        case "check":
          return (
            <M.CheckboxItem
              key={i}
              className="menu-item"
              checked={entry.checked}
              disabled={entry.disabled}
              onCheckedChange={entry.onChange}
              onSelect={(e) => entry.keepOpen && e.preventDefault()}
            >
              <span className="menu-indicator">
                <M.ItemIndicator>
                  <Check />
                </M.ItemIndicator>
              </span>
              <span className="menu-label">{entry.label}</span>
            </M.CheckboxItem>
          );
        case "sub":
          return (
            <M.Sub key={i}>
              <M.SubTrigger className="menu-item" disabled={!entry.entries}>
                <span className="menu-indicator" />
                <span className="menu-label">{entry.label}</span>
                <ChevronRight className="menu-chevron" />
              </M.SubTrigger>
              {entry.entries && (
                <M.Portal>
                  <M.SubContent className="menu" sideOffset={-2} alignOffset={-4}>
                    {render(entry.entries)}
                  </M.SubContent>
                </M.Portal>
              )}
            </M.Sub>
          );
      }
    });

  return <>{render(entries)}</>;
}
