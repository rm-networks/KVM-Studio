import { createContext, useContext } from "react";
import { useTranslation } from "react-i18next";

import type { CdromDevice, UsbDevice, VmSummary } from "../../api/client";
import { type MenuEntry, item, sep, sub } from "../../components/menuModel";
import { useConsole } from "../console/consoleRegistry";
import { COMBOS } from "../console/keys";
import { formatSize } from "../iso-picker/isoTree";
import { useLibraryActions } from "../library/libraryActionsContext";
import { POWER_ACTIONS, powerAllowed } from "./power";
import { useVmActions } from "./vmActionsContext";

/** What the VM menu does that lives in the main window (dialogs, tabs). */
export interface VmCommands {
  openTab: (vm: VmSummary) => void;
  settings: (vm: VmSummary) => void;
  snapshots: (vm: VmSummary) => void;
  guestTools: (vm: VmSummary) => void;
  changeMedia: (vm: VmSummary, target: string) => void;
  eject: (vm: VmSummary, target: string) => void;
  usb: (vm: VmSummary, device: UsbDevice, connect: boolean) => void;
}

export const VmCommandsContext = createContext<VmCommands | null>(null);

/**
 * The VM menu: the same entries, in the same order and the same state, in
 * the menu bar (VM menu) and when a VM of the library is right-clicked.
 * Without a VM every entry is greyed out.
 */
export function useVmMenu(
  vm: VmSummary | null,
  drives: CdromDevice[],
  usb: UsbDevice[],
): MenuEntry[] {
  const { t } = useTranslation();
  const actions = useVmActions();
  const library = useLibraryActions();
  const commands = useContext(VmCommandsContext);
  const vmConsole = useConsole(vm?.uuid);
  const m = (key: string) => t(`menu.${key}`);
  const on = (run: (vm: VmSummary) => void) => (vm ? () => run(vm) : undefined);

  const power = POWER_ACTIONS.map((action) =>
    item(
      t(`power.${action}`),
      undefined,
      vm && powerAllowed(vm.state, action) ? () => actions.power(vm, action) : undefined,
    ),
  );

  const removable: MenuEntry[] = drives.map((drive) =>
    sub(
      t("menu.cdrom", {
        target: drive.target,
        media: drive.path ? drive.path.slice(drive.path.lastIndexOf("/") + 1) : t("menu.noMedia"),
      }),
      [
        item(
          m("changeIso"),
          undefined,
          on((v) => commands?.changeMedia(v, drive.target)),
        ),
        item(
          m("eject"),
          undefined,
          drive.path ? on((v) => commands?.eject(v, drive.target)) : undefined,
        ),
      ],
    ),
  );
  const units: [string, string, string] = [t("units.mb"), t("units.gb"), t("units.kb")];
  const usbEntries: MenuEntry[] = usb.map((device) => {
    const here = vm !== null && device.vm === vm.uuid;
    const elsewhere = device.vm !== null && !here;
    const details = [
      device.size > 0 ? formatSize(device.size, units) : null,
      elsewhere ? t("menu.usbInVm", { name: device.vm_name }) : null,
      device.mountpoints.length ? t("menu.usbMounted", { path: device.mountpoints[0] }) : null,
    ].filter(Boolean);
    return {
      kind: "check",
      label: details.length ? `${device.name} (${details.join(", ")})` : device.name,
      checked: here,
      disabled: elsewhere || vm?.state !== "running",
      onChange: () => vm && commands?.usb(vm, device, !here),
    };
  });
  if (removable.length && usbEntries.length) removable.push(sep);
  removable.push(...usbEntries);

  const manage: MenuEntry[] = [
    item(m("clone"), undefined, on(actions.clone)),
    item(m("rename"), undefined, on(actions.rename)),
    item(
      t("library.moveTo"),
      undefined,
      on((v) => library.moveVm(v)),
    ),
    // Only when there is something to move.
    ...(vm?.files === "outside"
      ? [
          item(
            t("library.importFiles"),
            undefined,
            library.available ? on(library.importVm) : undefined,
          ),
        ]
      : []),
    ...(vm?.files === "loose" ? [item(t("library.tidyFiles"), undefined, on(library.tidyVm))] : []),
    sep,
    item(
      m("removeFromLibrary"),
      undefined,
      on((v) => actions.remove(v, false)),
    ),
    item(
      m("deleteFromDisk"),
      undefined,
      on((v) => actions.remove(v, true)),
    ),
  ];

  return [
    item(
      m("openTab"),
      undefined,
      on((v) => commands?.openTab(v)),
    ),
    sep,
    sub(m("power"), vm ? power : undefined),
    sub(m("removable"), removable.length ? removable : undefined),
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
    item(
      m("snapshotManager"),
      undefined,
      on((v) => commands?.snapshots(v)),
    ),
    sub(m("manage"), vm ? manage : undefined),
    item(
      m("guestTools"),
      undefined,
      vm?.state === "running" ? on((v) => commands?.guestTools(v)) : undefined,
    ),
    sep,
    item(
      m("settings"),
      ["Ctrl", "D"],
      on((v) => commands?.settings(v)),
    ),
  ];
}
