import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { UsbDevice } from "../api/client";
import { makeVm } from "../test/fixtures";
import { VmActionsProvider } from "../features/vm/VmActions";
import { NotificationProvider } from "../components/Notifications";
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

function open(menu: string) {
  const trigger = screen.getByRole("menuitem", { name: menu });
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false });
}

describe("MenuBar", () => {
  it("lists the host's USB storage under Removable Devices", async () => {
    const toggled: [string, boolean][] = [];
    const opened: string[] = [];
    const noop = () => undefined;
    render(
      <NotificationProvider>
        <VmActionsProvider>
          <MenuBar
            layout={{ library: true, toolbar: true, statusBar: true }}
            onToggle={noop}
            onAbout={noop}
            onNewVm={noop}
            onOpenDisk={noop}
            onSettings={noop}
            onGuestTools={noop}
            vmConsole={null}
            onAppFullscreen={noop}
            onGoHome={noop}
            tabs={[]}
            activeTab="home"
            onActivateTab={noop}
            drives={[]}
            onChangeMedia={noop}
            onEject={noop}
            usb={[
              key,
              { ...key, device: 12, name: "Kingston", mountpoints: [], vm: "x", vm_name: "W11" },
            ]}
            onUsb={(device, connect) => toggled.push([device.name, connect])}
            onMenuOpen={(menu) => opened.push(menu)}
            vm={makeVm({ uuid: "u1", name: "CLT-DEB13", state: "running" })}
          />
        </VmActionsProvider>
      </NotificationProvider>,
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
});
