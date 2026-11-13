import { fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { api, type UsbDevice, type VmSummary } from "../api/client";
import { NotificationProvider } from "../components/Notifications";
import { LibraryActionsProvider } from "../features/library/LibraryActions";
import { VmContextMenu } from "../features/library/VmContextMenu";
import { VmActionsProvider } from "../features/vm/VmActions";
import { type VmCommands, VmCommandsContext } from "../features/vm/vmMenu";
import { makeVm } from "../test/fixtures";
import { MenuBar } from "./MenuBar";

const key: UsbDevice = {
  bus: 2,
  device: 11,
  vendor_id: "0781",
  product_id: "556b",
  name: "SanDisk Cruzer Edge",
  size: 32010928128,
  disks: ["sdc"],
  mountpoints: ["/run/media/romain/USB-DISK"],
  in_use: [],
  vm: null,
  vm_name: null,
};

const noop = () => undefined;

function Providers({
  commands,
  children,
}: {
  commands?: Partial<VmCommands>;
  children: ReactNode;
}) {
  const all: VmCommands = {
    openTab: noop,
    settings: noop,
    snapshots: noop,
    guestTools: noop,
    changeMedia: noop,
    eject: noop,
    usb: noop,
    ...commands,
  };
  return (
    <NotificationProvider>
      <VmActionsProvider>
        <LibraryActionsProvider library={{ root: "/data/KVM-Studio/VM", folders: [], order: {} }}>
          <VmCommandsContext.Provider value={all}>{children}</VmCommandsContext.Provider>
        </LibraryActionsProvider>
      </VmActionsProvider>
    </NotificationProvider>
  );
}

function Bar({
  vm,
  usb = [],
  onMenuOpen,
}: {
  vm: VmSummary;
  usb?: UsbDevice[];
  onMenuOpen?: (m: string) => void;
}) {
  return (
    <MenuBar
      layout={{ library: true, toolbar: true, statusBar: true }}
      onToggle={noop}
      onAbout={noop}
      onNewVm={noop}
      onOpenDisk={noop}
      onAppFullscreen={noop}
      onGoHome={noop}
      tabs={[]}
      activeTab="home"
      onActivateTab={noop}
      drives={[]}
      usb={usb}
      onMenuOpen={onMenuOpen}
      vm={vm}
    />
  );
}

function open(menu: string) {
  const trigger = screen.getByRole("menuitem", { name: menu });
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false });
}

/** Entries of an open menu: label (with shortcut), greyed out or not, separators. */
function entriesOf(menu: HTMLElement) {
  return [...menu.children].map((el) =>
    el.getAttribute("role") === "separator"
      ? "---"
      : `${el.textContent ?? ""}${el.hasAttribute("data-disabled") ? " (disabled)" : ""}`,
  );
}

describe("MenuBar", () => {
  it("lists the host's USB storage under Removable Devices", async () => {
    const toggled: [string, boolean][] = [];
    const opened: string[] = [];
    render(
      <Providers commands={{ usb: (_vm, device, connect) => toggled.push([device.name, connect]) }}>
        <Bar
          vm={makeVm({ uuid: "u1", name: "CLT-DEB13", state: "running" })}
          usb={[
            key,
            { ...key, device: 12, name: "Kingston", mountpoints: [], vm: "x", vm_name: "W11" },
          ]}
          onMenuOpen={(menu) => opened.push(menu)}
        />
      </Providers>,
    );
    open("VM");
    expect(opened).toEqual(["vm"]);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Périphériques amovibles" }));
    const mounted = await screen.findByRole("menuitemcheckbox", {
      name: "SanDisk Cruzer Edge (29.8 Go, monté sur /run/media/romain/USB-DISK)",
    });
    const other = screen.getByRole("menuitemcheckbox", { name: /Kingston \(.*dans W11\)/ });
    expect(other.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(mounted);
    expect(toggled).toEqual([["SanDisk Cruzer Edge", true]]);
  });

  it.each(["running", "shutoff"] as const)(
    "has the same VM menu as the right click on a %s VM",
    async (state) => {
      vi.spyOn(api, "cdroms").mockResolvedValue([]);
      vi.spyOn(api, "usbDevices").mockResolvedValue([]);
      const vm = makeVm({ uuid: "u1", name: "CLT-DEB13", state, files: "loose" });

      const bar = render(
        <Providers>
          <Bar vm={vm} />
        </Providers>,
      );
      open("VM");
      const fromBar = entriesOf(await screen.findByRole("menu"));
      bar.unmount();

      render(
        <Providers>
          <VmContextMenu vm={vm}>
            <span>CLT-DEB13</span>
          </VmContextMenu>
        </Providers>,
      );
      fireEvent.contextMenu(screen.getByText("CLT-DEB13"));
      const fromTree = entriesOf(await screen.findByRole("menu"));

      expect(fromTree).toEqual(fromBar);
      expect(fromBar.length).toBeGreaterThan(10);
      expect(within(screen.getByRole("menu")).getByText("Paramètres…")).toBeTruthy();
    },
  );
});
