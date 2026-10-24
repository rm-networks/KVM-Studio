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
      const body = path.endsWith("/hardware") ? hardware : path === "/api/host" ? host : networks;
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
});
