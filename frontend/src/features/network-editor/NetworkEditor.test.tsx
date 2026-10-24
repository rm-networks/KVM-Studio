import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Network } from "../../api/client";
import { NotificationProvider } from "../../components/Notifications";
import { settingsFrom } from "./draft";
import { NetworkEditor } from "./NetworkEditor";

const kvmnet8: Network = {
  name: "kvmnet8",
  kind: "nat",
  forward_mode: "nat",
  bridge: "kvmnet8",
  managed: true,
  active: true,
  autostart: true,
  persistent: true,
  subnet: "192.168.108.0/24",
  host_ip: "192.168.108.1",
  dhcp: { start: "192.168.108.128", end: "192.168.108.254" },
  used_by: ["FW-OPN"],
};
const bridged: Network = {
  ...kvmnet8,
  name: "br-lan",
  kind: "other",
  forward_mode: "bridge",
  bridge: "br0",
  managed: false,
  subnet: null,
  host_ip: null,
  dhcp: null,
  used_by: [],
};

function mockApi() {
  const calls: { method: string; path: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push({ method, path, body: init?.body ? JSON.parse(init.body as string) : null });
      const body = method === "GET" && path === "/api/networks" ? [kvmnet8, bridged] : null;
      return Promise.resolve(
        new Response(body ? JSON.stringify(body) : null, { status: body ? 200 : 204 }),
      );
    }),
  );
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("NetworkEditor", () => {
  it("lists networks and applies an edit", async () => {
    const calls = mockApi();
    render(
      <NotificationProvider>
        <NetworkEditor onClose={() => undefined} />
      </NotificationProvider>,
    );
    expect(await screen.findByText("kvmnet8")).toBeTruthy();
    expect(screen.getByText("Utilisé par : FW-OPN")).toBeTruthy();

    fireEvent.click(screen.getByLabelText(/Host-only/));
    fireEvent.change(screen.getByDisplayValue("192.168.108.128"), {
      target: { value: "192.168.108.200" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Appliquer" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.path).toBe("/api/networks/kvmnet8");
    expect(put?.body).toEqual({
      kind: "host_only",
      subnet: "192.168.108.0/24",
      host_adapter: true,
      dhcp: { start: "192.168.108.200", end: "192.168.108.254" },
    });
  });

  it("shortens a long list of VMs and shows it all on hover", async () => {
    kvmnet8.used_by = ["FW-OPN", "SRV-AD", "CLT-1", "CLT-2"];
    mockApi();
    render(
      <NotificationProvider>
        <NetworkEditor onClose={() => undefined} />
      </NotificationProvider>,
    );
    const line = await screen.findByText("Utilisé par : FW-OPN, SRV-AD et 2 autres");
    expect(line.getAttribute("title")).toBe("FW-OPN, SRV-AD, CLT-1, CLT-2");
    kvmnet8.used_by = ["FW-OPN"];
  });

  it("explains that other network types are edited elsewhere", async () => {
    mockApi();
    render(
      <NotificationProvider>
        <NetworkEditor onClose={() => undefined} />
      </NotificationProvider>,
    );
    fireEvent.click(await screen.findByText("br-lan"));
    expect(screen.getByText(/se modifient dans virt-manager/)).toBeTruthy();
  });
});

describe("settingsFrom", () => {
  const base = {
    kind: "host_only" as const,
    ip: "10.5.0.0",
    mask: "255.255.255.0",
    hostAdapter: true,
    dhcpEnabled: false,
    dhcpStart: "",
    dhcpEnd: "",
  };

  it("drops the address for a lab segment", () => {
    expect(settingsFrom({ ...base, hostAdapter: false })).toEqual({
      settings: { kind: "host_only", host_adapter: false },
    });
  });

  it("always keeps the host address for NAT", () => {
    expect(settingsFrom({ ...base, kind: "nat", hostAdapter: false })).toEqual({
      settings: { kind: "nat", subnet: "10.5.0.0/24", host_adapter: true },
    });
  });

  it("reports bad fields", () => {
    expect(settingsFrom({ ...base, mask: "255.0.255.0" })).toEqual({ error: "subnet" });
    expect(settingsFrom({ ...base, dhcpEnabled: true })).toEqual({ error: "dhcp" });
  });
});
