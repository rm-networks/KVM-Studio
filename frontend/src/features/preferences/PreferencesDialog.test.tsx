import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Config } from "../../api/client";
import { NotificationProvider } from "../../components/Notifications";
import { PreferencesDialog } from "./PreferencesDialog";

const config: Config = {
  interface: { mode: "desktop" },
  web: { port: 8765, share_on_lan: false, tls: "auto", guest_enabled: true, login_max_attempts: 5 },
  libvirt: { uri: "qemu:///system" },
  storage: { vm_default_location: null },
  iso_libraries: [],
  defaults: { firmware: "uefi", disk_bus: "virtio", nic_model: "virtio", virtio_win_iso: null },
  ui: { theme: "system", language: "fr" },
};

function mockApi(restart = false) {
  const puts: Config[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
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
      };
      return Promise.resolve(new Response(JSON.stringify(path === "/api/preferences" ? body : {})));
    }),
  );
  return puts;
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

    fireEvent.click(screen.getByText("Bibliothèques ISO"));
    fireEvent.click(screen.getByRole("button", { name: "Ajouter" }));
    fireEvent.change(screen.getByDisplayValue("Nouvelle bibliothèque"), {
      target: { value: "ISO principales" },
    });
    fireEvent.change(screen.getAllByRole("textbox").at(-1) as HTMLElement, {
      target: { value: "/srv/iso" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Appliquer" }));
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]?.storage.vm_default_location).toBe("/media/romain/Data/VM");
    expect(puts[0]?.iso_libraries).toEqual([
      { name: "ISO principales", path: "/srv/iso", recursive: true },
    ]);
    expect(onSaved).toHaveBeenCalled();

    fireEvent.click(screen.getByText("Espace de travail"));
    expect(
      screen.getByText(
        "Les machines virtuelles sont rangées dans : /media/romain/Data/VM/KVM-Studio/VM",
      ),
    ).toBeTruthy();
  });

  it("tells when a restart is needed", async () => {
    mockApi(true);
    open();
    await screen.findByPlaceholderText("/srv/vm");
    fireEvent.click(screen.getByText("Interface"));
    fireEvent.click(screen.getByLabelText(/Web : dans le navigateur/));
    fireEvent.click(screen.getByRole("button", { name: "Appliquer" }));
    expect(await screen.findByText(/Redémarrez KVM Studio/)).toBeTruthy();
  });
});
