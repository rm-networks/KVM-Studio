import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Config } from "../../api/client";
import { NotificationProvider } from "../../components/Notifications";
import { PreferencesDialog } from "./PreferencesDialog";

const config: Config = {
  interface: { mode: "desktop" },
  web: {
    port: 60080,
    https_port: 60443,
    share_on_lan: false,
    tls: "auto",
    guest_enabled: true,
    login_max_attempts: 5,
  },
  libvirt: { uri: "qemu:///system" },
  storage: { vm_default_location: null },
  iso_libraries: [],
  defaults: { firmware: "uefi", disk_bus: "virtio", nic_model: "virtio", virtio_win_iso: null },
  ui: { theme: "system", language: "fr" },
};

function mockApi(restart = false) {
  const puts: Config[] = [];
  const added: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      if (path === "/api/preferences/iso-libraries") {
        const library = JSON.parse(init?.body as string) as Config["iso_libraries"][number];
        added.push(library);
        const change = {
          config: { ...config, iso_libraries: [{ ...library, extensions: [".iso", ".img"] }] },
          declared: true,
          removed_acls: [],
        };
        return Promise.resolve(new Response(JSON.stringify(change)));
      }
      if (init?.method === "PUT") {
        puts.push(JSON.parse(init.body as string) as Config);
        const root = "/media/romain/Data/VM/KVM-Studio/VM";
        return Promise.resolve(
          new Response(JSON.stringify({ restart_required: restart, library_root: root })),
        );
      }
      const body = {
        config,
        config_path: "/home/romain/.config/kvm-studio/config.toml",
        library_root: null,
        iso_declared: [],
      };
      return Promise.resolve(new Response(JSON.stringify(path === "/api/preferences" ? body : {})));
    }),
  );
  return Object.assign(puts, { added });
}

afterEach(() => vi.unstubAllGlobals());

function open(onSaved = () => undefined) {
  render(
    <NotificationProvider>
      <PreferencesDialog onClose={() => undefined} onSaved={onSaved} />
    </NotificationProvider>,
  );
}

describe("PreferencesDialog", () => {
  it("saves the VM location and an ISO library", async () => {
    const puts = mockApi();
    const onSaved = vi.fn();
    open(onSaved);
    const location = await screen.findByPlaceholderText("/srv/vm");
    fireEvent.change(location, { target: { value: "/media/romain/Data/VM" } });

    // A library is declared to the helper at once, through its own dialog.
    fireEvent.click(screen.getByText("Bibliothèques ISO"));
    fireEvent.click(screen.getByRole("button", { name: "Ajouter" }));
    fireEvent.change(screen.getByDisplayValue("Nouvelle bibliothèque"), {
      target: { value: "ISO principales" },
    });
    fireEvent.change(screen.getAllByRole("textbox").at(-1) as HTMLElement, {
      target: { value: "/srv/iso" },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Ajouter" }).at(-1) as HTMLElement);
    expect((await screen.findAllByText("/srv/iso")).length).toBeGreaterThan(0);
    expect(puts.added).toEqual([{ name: "ISO principales", path: "/srv/iso", recursive: true }]);

    fireEvent.click(screen.getByRole("button", { name: "Appliquer" }));
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]?.storage.vm_default_location).toBe("/media/romain/Data/VM");
    expect(puts[0]?.iso_libraries).toEqual([
      { name: "ISO principales", path: "/srv/iso", recursive: true, extensions: [".iso", ".img"] },
    ]);
    expect(onSaved).toHaveBeenCalled();

    fireEvent.click(screen.getByText("Espace de travail"));
    expect(
      screen.getByText(
        "Les machines virtuelles sont rangées dans : /media/romain/Data/VM/KVM-Studio/VM",
      ),
    ).toBeTruthy();
  });

  it("offers to restart with the web ports", async () => {
    mockApi(true);
    document.documentElement.dataset.mode = "desktop";
    open();
    await screen.findByPlaceholderText("/srv/vm");
    fireEvent.click(screen.getByText("Interface"));
    fireEvent.click(screen.getByLabelText(/Web : dans le navigateur/));
    fireEvent.click(screen.getByRole("button", { name: "Appliquer" }));
    expect(await screen.findByText(/http:\/\/127\.0\.0\.1:60080/)).toBeTruthy();
    expect(screen.queryByText(/60443/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Redémarrer maintenant" }));
    expect(await screen.findByText("KVM Studio redémarre…")).toBeTruthy();
  });
});
