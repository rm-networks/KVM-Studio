import * as Menubar from "@radix-ui/react-menubar";
import { Check, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { CdromDevice, VmSummary } from "../api/client";
import type { ConsoleHandle } from "../features/console/consoleRegistry";
import { COMBOS } from "../features/console/keys";
import { POWER_ACTIONS, powerAllowed } from "../features/vm/power";
import { useVmActions } from "../features/vm/vmActionsContext";
import type { Layout } from "./App";
import "./MenuBar.css";

type Entry =
  | { kind: "item"; label: string; keys?: string[]; onSelect?: () => void }
  | { kind: "sub"; label: string; entries?: Entry[] }
  | { kind: "check"; label: string; checked: boolean; onChange: () => void; keepOpen?: boolean }
  | { kind: "sep" };

const item = (label: string, keys?: string[], onSelect?: () => void): Entry => ({
  kind: "item",
  label,
  keys,
  onSelect,
});
const sub = (label: string, entries?: Entry[]): Entry => ({ kind: "sub", label, entries });
const sep: Entry = { kind: "sep" };

interface Props {
  layout: Layout;
  onToggle: (key: keyof Layout) => void;
  onAbout: () => void;
  onNetworkEditor: () => void;
  onPreferences: () => void;
  onFirstRun: () => void;
  onNewVm: () => void;
  onSettings: () => void;
  onGuestTools: () => void;
  vmConsole: ConsoleHandle | null;
  onFullscreen?: () => void;
  onAppFullscreen: () => void;
  onGoHome: () => void;
  onCloseTab?: () => void;
  onNextTab?: () => void;
  onPreviousTab?: () => void;
  /** Open tabs, Home first, for the Tabs menu. */
  tabs: { id: string; label: string }[];
  activeTab: string;
  onActivateTab: (id: string) => void;
  /** Closes the window; only in window mode. */
  onQuit?: () => void;
  drives: CdromDevice[];
  onChangeMedia: (target: string) => void;
  onEject: (target: string) => void;
  vm: VmSummary | null;
}

export function MenuBar({
  layout,
  onToggle,
  onAbout,
  onNetworkEditor,
  onPreferences,
  onFirstRun,
  onNewVm,
  onSettings,
  onGuestTools,
  vmConsole,
  onFullscreen,
  onAppFullscreen,
  onGoHome,
  onCloseTab,
  onNextTab,
  onPreviousTab,
  tabs,
  activeTab,
  onActivateTab,
  onQuit,
  drives,
  onChangeMedia,
  onEject,
  vm,
}: Props) {
  const { t } = useTranslation();
  const m = (key: string) => t(`menu.${key}`);
  const actions = useVmActions();
  const powerEntries: Entry[] = POWER_ACTIONS.map((action) =>
    item(
      t(`power.${action}`),
      undefined,
      vm && powerAllowed(vm.state, action) ? () => actions.power(vm, action) : undefined,
    ),
  );
  const removableEntries: Entry[] = drives.map((drive) =>
    sub(
      t("menu.cdrom", {
        target: drive.target,
        media: drive.path ? drive.path.slice(drive.path.lastIndexOf("/") + 1) : t("menu.noMedia"),
      }),
      [
        item(m("changeIso"), undefined, () => onChangeMedia(drive.target)),
        item(m("eject"), undefined, drive.path ? () => onEject(drive.target) : undefined),
      ],
    ),
  );
  const manageEntries: Entry[] = [
    item(m("clone"), undefined, vm ? () => actions.clone(vm) : undefined),
    item(m("rename"), undefined, vm ? () => actions.rename(vm) : undefined),
    sep,
    item(m("removeFromLibrary"), undefined, vm ? () => actions.remove(vm, false) : undefined),
    item(m("deleteFromDisk"), undefined, vm ? () => actions.remove(vm, true) : undefined),
  ];
  const check = (key: keyof Layout): Entry => ({
    kind: "check",
    label: m(key),
    checked: layout[key],
    onChange: () => onToggle(key),
    keepOpen: true,
  });

  // Only what works is listed: features still to come have no entry at all.
  const menus: [string, Entry[]][] = [
    [
      "file",
      [
        item(m("newVm"), ["Ctrl", "N"], onNewVm),
        sep,
        item(m("closeTab"), ["Ctrl", "W"], onCloseTab),
        ...(onQuit ? [sep, item(m("quit"), undefined, onQuit)] : []),
      ],
    ],
    [
      "edit",
      [
        item(m("networkEditor"), undefined, onNetworkEditor),
        item(m("preferences"), ["Ctrl", "P"], onPreferences),
      ],
    ],
    [
      "view",
      [
        item(m("fullscreen"), ["Ctrl", "Alt", "Enter"], onFullscreen),
        item(m("appFullscreen"), ["F11"], onAppFullscreen),
        sep,
        sub(m("customize"), [check("library"), check("toolbar"), check("statusBar")]),
      ],
    ],
    [
      "vm",
      [
        sub(m("power"), vm ? powerEntries : undefined),
        sub(m("removable"), removableEntries.length ? removableEntries : undefined),
        sep,
        item(m("sendCad"), undefined, vmConsole ? () => vmConsole.sendCtrlAltDel() : undefined),
        sub(
          m("sendKeys"),
          vmConsole
            ? COMBOS.map((c) =>
                item(t(`keys.combo.${c.id}`, { defaultValue: c.label }), undefined, () =>
                  vmConsole.sendKeys(c.keys),
                ),
              )
            : undefined,
        ),
        item(m("grab"), ["Ctrl", "G"], vmConsole ? () => vmConsole.grab() : undefined),
        sep,
        sub(m("manage"), vm ? manageEntries : undefined),
        item(m("guestTools"), undefined, vm?.state === "running" ? onGuestTools : undefined),
        sep,
        item(m("settings"), ["Ctrl", "D"], vm ? onSettings : undefined),
      ],
    ],
    [
      "tabs",
      [
        ...tabs.map((tab) => ({
          kind: "check" as const,
          label: tab.label,
          checked: tab.id === activeTab,
          onChange: () => onActivateTab(tab.id),
        })),
        sep,
        item(m("goHome"), undefined, onGoHome),
        sep,
        item(m("nextTab"), ["Ctrl", "Tab"], onNextTab),
        item(m("previousTab"), ["Ctrl", "Shift", "Tab"], onPreviousTab),
      ],
    ],
    [
      "help",
      [item(m("firstRun"), undefined, onFirstRun), sep, item(m("about"), undefined, onAbout)],
    ],
  ];

  const formatKeys = (keys: string[]) =>
    keys.map((k) => t(`keys.${k}`, { defaultValue: k })).join("+");

  const renderEntries = (entries: Entry[]) =>
    entries.map((entry, i) => {
      switch (entry.kind) {
        case "sep":
          return <Menubar.Separator key={i} className="menu-separator" />;
        case "item":
          return (
            <Menubar.Item
              key={i}
              className="menu-item"
              disabled={!entry.onSelect}
              onSelect={entry.onSelect}
            >
              <span className="menu-indicator" />
              <span className="menu-label">{entry.label}</span>
              {entry.keys && <span className="menu-keys">{formatKeys(entry.keys)}</span>}
            </Menubar.Item>
          );
        case "check":
          return (
            <Menubar.CheckboxItem
              key={i}
              className="menu-item"
              checked={entry.checked}
              onCheckedChange={entry.onChange}
              onSelect={(e) => entry.keepOpen && e.preventDefault()}
            >
              <span className="menu-indicator">
                <Menubar.ItemIndicator>
                  <Check />
                </Menubar.ItemIndicator>
              </span>
              <span className="menu-label">{entry.label}</span>
            </Menubar.CheckboxItem>
          );
        case "sub":
          return (
            <Menubar.Sub key={i}>
              <Menubar.SubTrigger className="menu-item" disabled={!entry.entries}>
                <span className="menu-indicator" />
                <span className="menu-label">{entry.label}</span>
                <ChevronRight className="menu-chevron" />
              </Menubar.SubTrigger>
              {entry.entries && (
                <Menubar.Portal>
                  <Menubar.SubContent className="menu" sideOffset={-2} alignOffset={-4}>
                    {renderEntries(entry.entries)}
                  </Menubar.SubContent>
                </Menubar.Portal>
              )}
            </Menubar.Sub>
          );
      }
    });

  return (
    <Menubar.Root className="menubar">
      {menus.map(([key, entries]) => (
        <Menubar.Menu key={key}>
          <Menubar.Trigger className="menubar-trigger">{m(key)}</Menubar.Trigger>
          <Menubar.Portal>
            <Menubar.Content className="menu" align="start" sideOffset={0}>
              {renderEntries(entries)}
            </Menubar.Content>
          </Menubar.Portal>
        </Menubar.Menu>
      ))}
    </Menubar.Root>
  );
}
