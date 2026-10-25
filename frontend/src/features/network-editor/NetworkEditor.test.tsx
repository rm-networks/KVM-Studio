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
  gateway: "host",
  gateway_ip: null,
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
};

const exported = { version: 1, networks: [{ name: "LAN-9", xml: "<network/>" }] };

function mockApi(plan = { restart: false, running: [] as string[] }) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push({ method, path, body: init?.body ? JSON.parse(init.body as string) : null });
      const body =
        method === "GET" && path === "/api/networks"
          ? [kvmnet8, bridged]
          : path.endsWith("/plan")
            ? plan
            : path.endsWith("/export")
              ? exported
              : path.endsWith("/import")
                ? { created: ["LAN-9"], skipped: [] }
                : null;
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
    expect(screen.queryByText(/Utilisé par/)).toBeNull();

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
      host_ip: "192.168.108.1",
      dhcp: { start: "192.168.108.200", end: "192.168.108.254" },
      gateway: "host",
      gateway_ip: null,
      stop_vms: null,
    });
  });

  it("asks before restarting a network that running VMs use", async () => {
    const calls = mockApi({ restart: true, running: ["FW-OPN"] });
    render(
      <NotificationProvider>
        <NetworkEditor onClose={() => undefined} />
      </NotificationProvider>,
    );
    fireEvent.change(await screen.findByPlaceholderText("192.168.108.1"), {
      target: { value: "192.168.108.254" },
    });
    expect(screen.getByText(/La plage DHCP sera 192.168.108.128 à 192.168.108.253/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Appliquer" }));
    expect(await screen.findByText(/Ces VMs sont éteintes.*FW-OPN/)).toBeTruthy();
    expect(calls.some((c) => c.method === "PUT")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "Les éteindre et appliquer" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({
      host_ip: "192.168.108.254",
      dhcp: { start: "192.168.108.128", end: "192.168.108.253" },
      stop_vms: "shutdown",
    });
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
    hostIp: "",
    dhcpEnabled: false,
    dhcpStart: "",
    dhcpEnd: "",
    gateway: "host" as const,
    gatewayIp: "",
  };

  it("drops the address for a lab segment", () => {
    expect(settingsFrom({ ...base, hostAdapter: false })).toEqual({
      settings: { kind: "host_only", host_adapter: false },
    });
  });

  it("always keeps the host address for NAT", () => {
    expect(settingsFrom({ ...base, kind: "nat", hostAdapter: false })).toEqual({
      settings: { kind: "nat", subnet: "10.5.0.0/24", host_adapter: true, host_ip: null },
    });
  });

  it("reports bad fields", () => {
    expect(settingsFrom({ ...base, mask: "255.0.255.0" })).toEqual({ error: "subnet" });
    expect(settingsFrom({ ...base, dhcpEnabled: true })).toEqual({ error: "dhcp" });
    expect(settingsFrom({ ...base, hostIp: "10.5.0.255" })).toEqual({ error: "hostIp" });
  });

  it("moves the DHCP range off the host address", () => {
    const draft = {
      ...base,
      hostIp: "10.5.0.254",
      dhcpEnabled: true,
      dhcpStart: "10.5.0.128",
      dhcpEnd: "10.5.0.254",
      gateway: "custom" as const,
      gatewayIp: "10.5.0.250",
    };
    const result = settingsFrom(draft);
    expect(result).toMatchObject({
      settings: {
        host_ip: "10.5.0.254",
        dhcp: { start: "10.5.0.128", end: "10.5.0.253" },
        gateway: "custom",
        gateway_ip: "10.5.0.250",
      },
    });
    expect(settingsFrom({ ...draft, kind: "nat" })).toMatchObject({
      settings: { gateway: "host", gateway_ip: null },
    });
  });
});
