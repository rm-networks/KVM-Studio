import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Config, SetupStatus } from "../../api/client";
import { NotificationProvider } from "../../components/Notifications";
import i18n from "../../i18n";
import { FirstRunWizard } from "./FirstRunWizard";

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
  workspace: { on_close: "keep", close_reminder: true },
  ui: { theme: "system", language: "fr", vm_tabs: true },
};

const status: SetupStatus = {
  needed: true,
  user: "alice",
  checks: [
    { id: "cpu", level: "ok", detail: "intel" },
    { id: "kvm", level: "ok", detail: "kvm_intel" },
    { id: "nested", level: "warn", detail: "kvm_intel" },
    { id: "libvirt", level: "ok", detail: "libvirt 12.0.0 (qemu:///system)" },
  ],
  libvirt_group: "not_member",
  networks: [
    { name: "kvmnet1", kind: "host_only", subnet: "192.168.101.0/24", exists: false },
    { name: "kvmnet8", kind: "nat", subnet: "192.168.108.0/24", exists: true },
  ],
};

function mockApi() {
  const calls: { method: string; path: string; body?: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push({ method, path, body: init?.body ? JSON.parse(init.body as string) : undefined });
      const answers: Record<string, unknown> = {
        "GET /api/setup": status,
        "GET /api/preferences": { config, config_path: null, library_root: null },
        "POST /api/setup/libvirt-group": { libvirt_group: "relogin" },
        "PUT /api/preferences": { restart_required: false, library_root: "/srv/vm/KVM-Studio/VM" },
        "POST /api/preferences/iso-libraries": { config, declared: true, removed_acls: [] },
        "POST /api/setup/networks": ["kvmnet1"],
      };
      return Promise.resolve(new Response(JSON.stringify(answers[`${method} ${path}`])));
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

const next = () => fireEvent.click(screen.getByRole("button", { name: "Suivant >" }));

describe("FirstRunWizard", () => {
  it("checks the host, joins the group, saves the locations and creates networks", async () => {
    const calls = mockApi();
    const onSaved = vi.fn();
    render(
      <NotificationProvider>
        <FirstRunWizard onClose={() => undefined} onSaved={onSaved} />
      </NotificationProvider>,
    );
    await waitFor(() => expect(calls.length).toBe(2));
    next();
    expect(await screen.findByText("Virtualisation matérielle disponible (intel)")).toBeTruthy();
    expect(screen.getByText("Virtualisation imbriquée inactive")).toBeTruthy();
    next();
    fireEvent.click(screen.getByRole("button", { name: "Ajouter mon compte au groupe libvirt" }));
    expect(await screen.findByText("Le compte alice a été ajouté au groupe libvirt.")).toBeTruthy();
    next();
    const [vm, iso] = screen.getAllByRole("textbox") as [HTMLElement, HTMLElement];
    const nextButton = screen.getByRole("button", { name: "Suivant >" });
    expect((nextButton as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(vm, { target: { value: "/srv/vm" } });
    fireEvent.change(iso, { target: { value: "/srv/iso" } });
    next();
    next();
    expect(screen.getByText("déjà présent")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Terminer" }));
    expect(await screen.findByText("Réseaux créés : kvmnet1.")).toBeTruthy();
    expect(screen.getByText(/Fermez votre session/)).toBeTruthy();
    expect(onSaved).toHaveBeenCalled();
    const saved = calls.find((c) => c.method === "PUT")?.body as Config;
    expect(saved.storage.vm_default_location).toBe("/srv/vm");
    expect(saved.iso_libraries).toEqual([]);
    const added = calls.find((c) => c.path === "/api/preferences/iso-libraries")?.body;
    expect(added).toEqual({ name: "ISO", path: "/srv/iso", recursive: true });
    expect(calls.some((c) => c.path === "/api/setup/networks")).toBe(true);
  });

  it("offers the language first and applies it at once", async () => {
    const calls = mockApi();
    const onSaved = vi.fn();
    render(
      <NotificationProvider>
        <FirstRunWizard onClose={() => undefined} onSaved={onSaved} />
      </NotificationProvider>,
    );
    const french = await screen.findByRole("radio", { name: "Français" });
    await waitFor(() => expect(french).toHaveProperty("checked", true));
    fireEvent.click(screen.getByRole("radio", { name: "English" }));
    expect(await screen.findByRole("button", { name: "Next >" })).toBeTruthy();
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    const saved = calls.find((c) => c.method === "PUT")?.body as Config;
    expect(saved.ui.language).toBe("en");
    await act(() => i18n.changeLanguage("fr"));
  });
});
