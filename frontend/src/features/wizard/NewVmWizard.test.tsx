import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationProvider } from "../../components/Notifications";
import { makeVm } from "../../test/fixtures";
import { NewVmWizard } from "./NewVmWizard";

const profiles = [
  {
    id: "linux",
    family: "linux",
    memory_mib: 2048,
    vcpus: 2,
    disk_gib: 25,
    disk_bus: "virtio",
    nic_model: "virtio",
    nics: 1,
    uefi: true,
    secure_boot: false,
    tpm: false,
    serial: false,
    nested: false,
  },
  {
    id: "firewall",
    family: "bsd",
    memory_mib: 2048,
    vcpus: 2,
    disk_gib: 20,
    disk_bus: "virtio",
    nic_model: "virtio",
    nics: 3,
    uefi: true,
    secure_boot: false,
    tpm: false,
    serial: true,
    nested: false,
  },
];
const host = {
  cpus: 8,
  memory_mib: 32768,
  disk_buses: ["virtio", "scsi", "sata", "nvme"],
  nic_models: ["virtio", "e1000e"],
  uefi: true,
  secure_boot: true,
  tpm: true,
};
const networks = [
  {
    name: "kvmnet1",
    kind: "host_only",
    forward_mode: null,
    bridge: "kvmnet1",
    managed: true,
    active: true,
    autostart: true,
    persistent: true,
    subnet: null,
    host_ip: null,
    dhcp: null,
    used_by: [],
  },
  {
    name: "kvmnet8",
    kind: "nat",
    forward_mode: "nat",
    bridge: "kvmnet8",
    managed: true,
    active: true,
    autostart: true,
    persistent: true,
    subnet: null,
    host_ip: null,
    dhcp: null,
    used_by: [],
  },
];

function mockApi() {
  const posts: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posts.push(JSON.parse(init.body as string));
        return Promise.resolve(new Response(JSON.stringify({ uuid: "new-uuid" }), { status: 201 }));
      }
      const body =
        path === "/api/profiles"
          ? profiles
          : path === "/api/host"
            ? host
            : path === "/api/networks"
              ? networks
              : {};
      return Promise.resolve(new Response(JSON.stringify(body)));
    }),
  );
  return posts;
}

afterEach(() => vi.unstubAllGlobals());

describe("NewVmWizard", () => {
  it("creates a firewall with three cards in a library folder", async () => {
    const posts = mockApi();
    const onCreated = vi.fn();
    render(
      <NotificationProvider>
        <NewVmWizard
          library={{ root: "/data/KVM-Studio/VM", folders: ["Labs"] }}
          vms={[makeVm({ name: "Firewall - BSD" })]}
          onCreated={onCreated}
          onClose={() => undefined}
        />
      </NotificationProvider>,
    );
    fireEvent.click(await screen.findByLabelText(/installerai le système plus tard/));
    fireEvent.click(screen.getByRole("button", { name: "Suivant >" }));

    fireEvent.click(await screen.findByText("Firewall / BSD"));
    fireEvent.click(screen.getByRole("button", { name: "Suivant >" }));

    // The default name avoids the one already taken.
    expect(screen.getByDisplayValue("Firewall - BSD-2")).toBeTruthy();
    fireEvent.change(screen.getByDisplayValue("Firewall - BSD-2"), { target: { value: "FW-OPN" } });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "Labs" } });
    expect(screen.getByText("/data/KVM-Studio/VM/Labs/FW-OPN")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Suivant >" }));

    fireEvent.click(screen.getByLabelText("Allouer tout l'espace maintenant"));
    fireEvent.click(screen.getByRole("button", { name: "Suivant >" }));

    expect(screen.getByText("kvmnet8 (virtio), kvmnet1 (virtio), kvmnet1 (virtio)")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Terminer" }));

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({
      name: "FW-OPN",
      folder: "Labs",
      profile: "firewall",
      iso: null,
      disk_gib: 20,
      disk_bus: "virtio",
      preallocate: true,
      nics: [
        { network: "kvmnet8", model: "virtio" },
        { network: "kvmnet1", model: "virtio" },
        { network: "kvmnet1", model: "virtio" },
      ],
      start: true,
    });
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("new-uuid", "FW-OPN"));
  });

  it("asks for a VM location first", async () => {
    mockApi();
    render(
      <NotificationProvider>
        <NewVmWizard
          library={{ root: null, folders: [] }}
          vms={[]}
          onCreated={() => undefined}
          onClose={() => undefined}
        />
      </NotificationProvider>,
    );
    fireEvent.click(await screen.findByLabelText(/installerai le système plus tard/));
    fireEvent.click(screen.getByRole("button", { name: "Suivant >" }));
    fireEvent.click(screen.getByRole("button", { name: "Suivant >" }));
    expect(screen.getByText(/Aucun emplacement des machines virtuelles/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Suivant >" }).hasAttribute("disabled")).toBe(true);
  });
});
