import * as Menubar from "@radix-ui/react-menubar";
import { useTranslation } from "react-i18next";

import type { CdromDevice, UsbDevice, VmSummary } from "../api/client";
import { MenuEntries } from "../components/MenuEntries";
import { type MenuEntry as Entry, item, sep, sub } from "../components/menuModel";
import { LANGUAGE_NAMES, languages, type Language } from "../i18n";
import { setAutofit, useAutofit } from "../features/console/consoleRegistry";
import { useVmMenu } from "../features/vm/vmMenu";
import type { Layout } from "./App";
import "./MenuBar.css";

interface Props {
  layout: Layout;
  onToggle: (key: keyof Layout) => void;
  onAbout: () => void;
  /** Host settings: none for a guest of LAN sharing. */
  onNetworkEditor?: () => void;
  onPreferences?: () => void;
  onFirstRun?: () => void;
  /** Guest of LAN sharing: ends the session. */
  onLogout?: () => void;
  /** Guest of LAN sharing: their own language, the only setting they have. */
  guestLanguage?: { current: string; onChange: (language: Language) => void };
  onNewVm: () => void;
  /** File > Open: a disk image to build a VM around. */
  onOpenDisk: () => void;
  /** Host files: none for a guest of LAN sharing. */
  onScan?: () => void;
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
  /** USB storage of the host: connected to this VM, or not. */
  usb: UsbDevice[];
  /** A menu of the bar opened (its key), to refresh what it lists. */
  onMenuOpen?: (menu: string) => void;
  vm: VmSummary | null;
}

export function MenuBar({
  layout,
  onToggle,
  onAbout,
  onNetworkEditor,
  onPreferences,
  onFirstRun,
  onLogout,
  guestLanguage,
  onNewVm,
  onOpenDisk,
  onScan,
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
  usb,
  onMenuOpen,
  vm,
}: Props) {
  const { t } = useTranslation();
  const autofit = useAutofit();
  const m = (key: string) => t(`menu.${key}`);
  const vmEntries = useVmMenu(vm, drives, usb);
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
        item(m("open"), undefined, onOpenDisk),
        ...(onScan ? [item(m("scan"), undefined, onScan)] : []),
        sep,
        item(m("closeTab"), ["Ctrl", "W"], onCloseTab),
        ...(onQuit ? [sep, item(m("quit"), undefined, onQuit)] : []),
        ...(onLogout ? [sep, item(m("logout"), undefined, onLogout)] : []),
      ],
    ],
    [
      "edit",
      guestLanguage
        ? [
            // The host's settings stay out of reach, greyed out.
            item(m("networkEditor")),
            item(m("preferences"), ["Ctrl", "P"]),
            sep,
            sub(
              m("language"),
              languages.map((language) => ({
                kind: "check" as const,
                // Each language under its own name, whatever the current one.
                label: LANGUAGE_NAMES[language],
                checked: guestLanguage.current === language,
                onChange: () => guestLanguage.onChange(language),
              })),
            ),
          ]
        : [
            ...(onNetworkEditor ? [item(m("networkEditor"), undefined, onNetworkEditor)] : []),
            ...(onPreferences ? [item(m("preferences"), ["Ctrl", "P"], onPreferences)] : []),
          ],
    ],
    [
      "view",
      [
        item(m("fullscreen"), ["Ctrl", "Alt", "Enter"], onFullscreen),
        item(m("appFullscreen"), ["F11"], onAppFullscreen),
        {
          kind: "check",
          label: m("autofit"),
          checked: autofit,
          onChange: () => setAutofit(!autofit),
          keepOpen: true,
        },
        sep,
        sub(m("customize"), [check("library"), check("toolbar"), check("statusBar")]),
      ],
    ],
    ["vm", vmEntries],
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
      [
        ...(onFirstRun ? [item(m("firstRun"), undefined, onFirstRun), sep] : []),
        item(m("about"), undefined, onAbout),
      ],
    ],
  ];

  return (
    <Menubar.Root className="menubar" onValueChange={(menu) => menu && onMenuOpen?.(menu)}>
      {menus
        .filter(([, entries]) => entries.length > 0)
        .map(([key, entries]) => (
          <Menubar.Menu key={key} value={key}>
            <Menubar.Trigger className="menubar-trigger">{m(key)}</Menubar.Trigger>
            <Menubar.Portal>
              <Menubar.Content className="menu" align="start" sideOffset={0}>
                <MenuEntries entries={entries} kind="menubar" />
              </Menubar.Content>
            </Menubar.Portal>
          </Menubar.Menu>
        ))}
    </Menubar.Root>
  );
}
