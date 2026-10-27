import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationProvider } from "../../components/Notifications";
import { makeVm } from "../../test/fixtures";
import { VmSettings } from "./VmSettings";

const hardware = {
  memory_mib: 2048,
  vcpus: 2,
  active: true,
  disks: [{ target: "vda", bus: "virtio", path: "/data/FW/FW.qcow2", format: "qcow2" }],
  cdroms: [{ target: "sda", bus: "sata", path: null, format: "raw" }],
  nics: [
    {
      mac: "52:54:00:aa:bb:cc",
      network: "kvmnet8",
      model: "virtio",
      target: "ks-abc123-0",
      connected: true,
    },
  ],
};
const host = {
  cpus: 8,
  memory_mib: 32768,
  disk_buses: ["virtio"],
  nic_models: ["virtio", "e1000e"],
  uefi: true,
  secure_boot: true,
  tpm: true,
};
const options = {
  name: "FW-OPN",
  profile: "firewall",
  active: false,
  installed: true,
  autostart: false,
  on_reboot: "restart",
  on_crash: "destroy",
  firmware: "uefi",
  secure_boot: false,
  tpm: true,
  boot_menu: true,
  boot: [
    { kind: "disk", id: "vda", detail: "FW.qcow2", enabled: true },
    { kind: "cdrom", id: "sda", detail: "", enabled: true },
    { kind: "nic", id: "52:54:00:aa:bb:cc", detail: "kvmnet8", enabled: false },
  ],
  clipboard: true,
  reset_nvram_pending: false,
  notes: "",
};
const networks = [
  { name: "kvmnet8", kind: "nat" },
  { name: "LAN-1", kind: "host_only" },
];

function mockApi() {
  const calls: { method: string; path: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method !== "GET") {
        calls.push({ method, path, body: init?.body ? JSON.parse(init.body as string) : null });
        return Promise.resolve(
          new Response(JSON.stringify({ restart_required: method === "PUT" })),
        );
      }
      const body = path.endsWith("/hardware")
        ? hardware
        : path.endsWith("/options")
          ? options
          : path === "/api/host"
            ? host
            : networks;
      return Promise.resolve(new Response(JSON.stringify(body)));
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("VmSettings", () => {
  it("changes memory and moves a card to another network", async () => {
    const calls = mockApi();
    render(
      <NotificationProvider>
        <VmSettings
          vm={makeVm({ uuid: "u1", name: "FW-OPN", state: "running" })}
          onClose={() => undefined}
        />
      </NotificationProvider>,
    );
    fireEvent.change(await screen.findByDisplayValue("2048"), { target: { value: "4096" } });
    fireEvent.click(screen.getByText("Carte réseau 1"));
    fireEvent.change(screen.getByDisplayValue("kvmnet8"), { target: { value: "LAN-1" } });
    fireEvent.click(screen.getByLabelText("Connectée (câble branché)"));
    fireEvent.click(screen.getByRole("button", { name: "Appliquer" }));

    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[0]).toEqual({
      method: "PUT",
      path: "/api/vms/u1/hardware/cpu-memory",
      body: { memory_mib: 4096, vcpus: 2 },
    });
    expect(calls[1]).toEqual({
      method: "PATCH",
      path: "/api/vms/u1/nics/52%3A54%3A00%3Aaa%3Abb%3Acc",
      body: { network: "LAN-1", connected: false },
    });
    expect(await screen.findByText(/prochain démarrage de la machine virtuelle/)).toBeTruthy();
  });

  it("saves the notes into the VM description", async () => {
    const calls = mockApi();
    render(
      <NotificationProvider>
        <VmSettings vm={makeVm({ uuid: "u1", name: "FW-OPN" })} onClose={() => undefined} />
      </NotificationProvider>,
    );
    fireEvent.click(await screen.findByRole("tab", { name: "Options" }));
    fireEvent.change(screen.getByLabelText("Notes"), { target: { value: "WAN on LAN-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Appliquer" }));
    await waitFor(() =>
      expect(calls).toEqual([
        { method: "PUT", path: "/api/vms/u1/notes", body: { notes: "WAN on LAN-1" } },
      ]),
    );
  });

  it("generates a new MAC address only when the VM is off", async () => {
    const calls = mockApi();
    const { unmount } = render(
      <NotificationProvider>
        <VmSettings vm={makeVm({ uuid: "u1", name: "FW-OPN" })} onClose={() => undefined} />
      </NotificationProvider>,
    );
    fireEvent.click(await screen.findByText("Carte réseau 1"));
    expect(screen.getByRole("button", { name: "Générer" }).hasAttribute("disabled")).toBe(true);
    unmount();
    hardware.active = false;
    render(
      <NotificationProvider>
        <VmSettings vm={makeVm({ uuid: "u1", name: "FW-OPN" })} onClose={() => undefined} />
      </NotificationProvider>,
    );
    fireEvent.click(await screen.findByText("Carte réseau 1"));
    fireEvent.click(screen.getByRole("button", { name: "Générer" }));
    hardware.active = true;
    await waitFor(() =>
      expect(calls[0]).toEqual({
        method: "POST",
        path: "/api/vms/u1/nics/52%3A54%3A00%3Aaa%3Abb%3Acc/new-mac",
        body: null,
      }),
    );
  });

  it("asks before removing a card", async () => {
    const calls = mockApi();
    render(
      <NotificationProvider>
        <VmSettings vm={makeVm({ uuid: "u1", name: "FW-OPN" })} onClose={() => undefined} />
      </NotificationProvider>,
    );
    fireEvent.click(await screen.findByText("Carte réseau 1"));
    fireEvent.click(screen.getByRole("button", { name: "Retirer" }));
    expect(screen.getByText("Retirer cette carte réseau de la machine virtuelle ?")).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", { name: "Retirer" }).at(-1) as HTMLElement);
    await waitFor(() => expect(calls[0]?.method).toBe("DELETE"));
  });

  it("changes the boot order and asks before removing the TPM of an installed VM", async () => {
    const calls = mockApi();
    const onClose = vi.fn();
    render(
      <NotificationProvider>
        <VmSettings vm={makeVm({ uuid: "u1", name: "FW-OPN" })} onClose={onClose} />
      </NotificationProvider>,
    );
    fireEvent.click(await screen.findByRole("tab", { name: "Options" }));
    fireEvent.click(screen.getByText("Firmware et démarrage"));
    fireEvent.click(screen.getByLabelText("Carte réseau (52:54:00:aa:bb:cc)"));
    fireEvent.click(
      screen.getByRole("button", { name: "Monter Carte réseau (52:54:00:aa:bb:cc)" }),
    );
    fireEvent.click(screen.getByLabelText("CD/DVD (sda)"));
    fireEvent.click(screen.getByLabelText("TPM 2.0 (émulé)"));
    expect(screen.getByText(/peut l'empêcher de démarrer/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "OK" }));
    expect(await screen.findByText("Modifier le firmware ou le TPM ?")).toBeTruthy();
    expect(calls).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Appliquer quand même" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toEqual({
      method: "PUT",
      path: "/api/vms/u1/options",
      body: {
        tpm: false,
        boot: [
          { kind: "disk", id: "vda", enabled: true },
          { kind: "nic", id: "52:54:00:aa:bb:cc", enabled: true },
          { kind: "cdrom", id: "sda", enabled: false },
        ],
        confirmed: true,
      },
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("needs at least one boot device", async () => {
    mockApi();
    render(
      <NotificationProvider>
        <VmSettings vm={makeVm({ uuid: "u1", name: "FW-OPN" })} onClose={() => undefined} />
      </NotificationProvider>,
    );
    fireEvent.click(await screen.findByRole("tab", { name: "Options" }));
    fireEvent.click(screen.getByText("Firmware et démarrage"));
    fireEvent.click(screen.getByLabelText("Disque dur (vda)"));
    fireEvent.click(screen.getByLabelText("CD/DVD (sda)"));
    expect(screen.getByText("Cochez au moins un périphérique de démarrage.")).toBeTruthy();
    expect((screen.getByRole("button", { name: "OK" }) as HTMLButtonElement).disabled).toBe(true);
  });
});
