import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { UninstallPlan } from "../../api/client";
import { NotificationProvider } from "../../components/Notifications";
import { UninstallWizard } from "./UninstallWizard";

const plan: UninstallPlan = {
  plan_id: "abc123",
  library_root: "/srv/vm/KVM-Studio/VM",
  vms: [
    {
      uuid: "u1",
      name: "web",
      delete: ["/srv/vm/KVM-Studio/VM/Lab/web/web.qcow2"],
      keep: [{ path: "/srv/iso/debian.iso", reason: "iso" }],
    },
  ],
  running: [],
  kept_vms: ["outside"],
  extra_files: ["/srv/vm/KVM-Studio/VM/notes.txt"],
  keep: [],
  networks: [
    { name: "LAN-1", bridge: "kvmnet3", used_by_kept: ["outside"], used_by_deleted: ["web"] },
    { name: "kvmnet8", bridge: "kvmnet8", used_by_kept: [], used_by_deleted: [] },
  ],
  iso_libraries: [],
  iso_acl_entries: 0,
  settings: ["/home/alice/.config/kvm-studio/config.toml"],
  packaged: false,
};

function mockApi(answer: Partial<UninstallPlan> = {}) {
  const posts: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      if (init?.method === "POST" && path === "/api/uninstall") {
        posts.push(JSON.parse(init.body as string));
        return Promise.resolve(
          new Response(
            JSON.stringify({
              deleted_vms: ["web"],
              failed_files: [],
              deleted_networks: ["kvmnet8"],
              kept_networks: ["LAN-1"],
              deleted_settings: false,
            }),
          ),
        );
      }
      return Promise.resolve(new Response(JSON.stringify({ ...plan, ...answer })));
    }),
  );
  return posts;
}

afterEach(() => vi.unstubAllGlobals());

const click = (name: string) => fireEvent.click(screen.getByRole("button", { name }));

describe("UninstallWizard", () => {
  it("lists the exact files and asks for a confirmation before deleting VMs", async () => {
    const posts = mockApi();
    render(
      <NotificationProvider>
        <UninstallWizard />
      </NotificationProvider>,
    );
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "Suivant >" }) as HTMLButtonElement).disabled,
      ).toBe(false),
    );
    click("Suivant >");
    expect(
      screen.getByText(
        /Machines virtuelles créées hors de KVM Studio, toujours conservées : outside/,
      ),
    ).toBeTruthy();
    fireEvent.click(screen.getByLabelText(/Supprimer la machine virtuelle créée par KVM Studio/));
    expect(screen.getByText("/srv/vm/KVM-Studio/VM/Lab/web/web.qcow2")).toBeTruthy();
    expect(screen.getByText("/srv/vm/KVM-Studio/VM/notes.txt")).toBeTruthy();
    expect(screen.getByText("/srv/iso/debian.iso (image ISO)")).toBeTruthy();
    const next = screen.getByRole("button", { name: "Suivant >" }) as HTMLButtonElement;
    expect(next.disabled).toBe(true);
    fireEvent.click(
      screen.getByLabelText("Je confirme la suppression définitive de ces 2 fichiers"),
    );
    expect(next.disabled).toBe(false);
    click("Suivant >");
    fireEvent.click(screen.getByLabelText(/Supprimer les réseaux kvmnet/));
    // With the VMs deleted, only the VMs that stay still hold a network.
    expect(screen.getByText("conservé, utilisé par outside")).toBeTruthy();
    click("Suivant >");
    expect(screen.getByText(/Aucun droit d'accès/)).toBeTruthy();
    click("Suivant >");
    click("Suivant >");
    expect(screen.getByText("rien à retirer (lancé depuis les sources)")).toBeTruthy();
    click("Désinstaller");
    expect(await screen.findByText("Désinstallation terminée.")).toBeTruthy();
    expect(screen.getByText("Réseaux conservés car encore utilisés : LAN-1")).toBeTruthy();
    expect(posts).toEqual([
      {
        plan_id: "abc123",
        delete_vms: true,
        delete_networks: true,
        delete_settings: false,
        remove_iso_acls: false,
      },
    ]);
  });

  it("refuses to go on while a VM to delete is running", async () => {
    mockApi({ running: ["web"] });
    render(
      <NotificationProvider>
        <UninstallWizard />
      </NotificationProvider>,
    );
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "Suivant >" }) as HTMLButtonElement).disabled,
      ).toBe(false),
    );
    click("Suivant >");
    fireEvent.click(screen.getByLabelText(/Supprimer la machine virtuelle/));
    expect(screen.getByText("Éteignez d'abord : web")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Suivant >" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
  });
});
