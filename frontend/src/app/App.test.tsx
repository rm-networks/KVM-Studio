import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { captureToken } from "../api/token";
import { FakeWebSocket } from "../test/fakeWebSocket";
import { makeVm } from "../test/fixtures";
import { App } from "./App";

const info = {
  version: "0.1.0.dev0",
  mode: "desktop",
  libvirt: {
    uri: "qemu:///system",
    hostname: "host",
    driver: "QEMU",
    libvirt_version: "12.0.0",
    hypervisor_version: "10.2.2",
  },
  ui: { theme: "system", language: "fr" },
};

const vms = [
  makeVm({ uuid: "1", name: "FW-VYOS", state: "running" }),
  makeVm({ uuid: "2", name: "CLT-DEB13" }),
];
const library = { root: null, folders: [] };

function apiResponse(path: string): unknown {
  if (path === "/api/info") return info;
  if (path === "/api/library") return library;
  return vms;
}

function mockFetch(handler: (path: string, init?: RequestInit) => [number, unknown]) {
  const fetchMock = vi.fn((path: string, init?: RequestInit) => {
    const [status, body] = handler(path, init);
    return Promise.resolve(new Response(JSON.stringify(body), { status }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

function eventSocket(): FakeWebSocket {
  const socket = FakeWebSocket.instances.find((s) => s.url.endsWith("/ws/events"));
  if (!socket) throw new Error("no event socket");
  return socket;
}

describe("App", () => {
  it("sends the token from the URL and lists the VMs", async () => {
    window.history.replaceState(null, "", "/#token=abc123");
    captureToken();
    expect(window.location.hash).toBe("");

    const fetchMock = mockFetch((path) => [200, apiResponse(path)]);
    render(<App />);

    expect(await screen.findByText("FW-VYOS")).toBeTruthy();
    expect(screen.getByText("CLT-DEB13")).toBeTruthy();
    expect(screen.getByText("2 machines virtuelles, 1 allumée")).toBeTruthy();
    expect(screen.getByText("Connecté à qemu:///system")).toBeTruthy();

    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer abc123");
  });

  it("tells at start that a kernel update needs a reboot", async () => {
    const broken = {
      ...info,
      kvm: { problem: "reboot_needed", kernel: "6.17.1", module: "kvm_intel" },
    };
    mockFetch((path) => [200, path === "/api/info" ? broken : apiResponse(path)]);
    render(<App />);
    expect(await screen.findByText("KVM n'est pas disponible")).toBeTruthy();
    expect(screen.getByText(/Redémarrez l'ordinateur pour utiliser le nouveau noyau/)).toBeTruthy();
  });

  it("explains an invalid session", async () => {
    mockFetch(() => [
      401,
      { error: { code: "auth.invalid_token", detail: "Missing or invalid session token" } },
    ]);
    render(<App />);
    expect(await screen.findByText(/Session invalide/)).toBeTruthy();
  });

  it("shows libvirt errors with the raw message", async () => {
    mockFetch(() => [
      503,
      { error: { code: "libvirt.unreachable", detail: "Failed to connect socket" } },
    ]);
    render(<App />);
    expect(await screen.findByText(/Impossible de joindre libvirt/)).toBeTruthy();
    expect(screen.getByText("Failed to connect socket")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Réessayer" })).toBeTruthy();
  });

  it("follows live state changes from the event socket", async () => {
    mockFetch((path) => [200, apiResponse(path)]);
    render(<App />);
    await screen.findByText("2 machines virtuelles, 1 allumée");
    const socket = eventSocket();
    expect(socket.protocols[0]).toBe("kvmstudio.events");

    act(() => {
      socket.open();
      socket.push({ type: "vm.changed", vm: { ...vms[1], state: "running" } });
    });
    expect(screen.getByText("2 machines virtuelles, 2 allumées")).toBeTruthy();

    act(() => socket.push({ type: "vm.removed", uuid: "1" }));
    expect(screen.queryByText("FW-VYOS")).toBeNull();
    expect(screen.getByText("1 machine virtuelle, 1 allumée")).toBeTruthy();

    act(() => socket.push({ type: "connection", state: "lost" }));
    expect(screen.getByText(/Connexion à libvirt perdue/)).toBeTruthy();
  });

  it("titles a VM tab with the VM name, whatever happens to the list", async () => {
    let listed = vms;
    const fetchMock = mockFetch((path) => [200, path === "/api/vms" ? listed : apiResponse(path)]);
    render(<App />);
    fireEvent.click(await screen.findByText("CLT-DEB13"));
    const tabLabels = () => screen.getAllByRole("tab").map((tab) => tab.textContent);
    expect(tabLabels()).toEqual(["Accueil", "CLT-DEB13"]);
    const socket = eventSocket();
    act(() => socket.open());

    // libvirt renames a domain by undefining and defining it again.
    listed = [vms[0] as (typeof vms)[number]];
    act(() => socket.push({ type: "vm.removed", uuid: "2" }));
    expect(tabLabels()).toEqual(["Accueil", "CLT-DEB13"]);
    act(() => socket.push({ type: "vm.changed", vm: { ...vms[1], name: "CLT-DEB13-b" } }));
    expect(tabLabels()).toEqual(["Accueil", "CLT-DEB13-b"]);
    expect(tabLabels().join()).not.toContain("2");

    // A VM missing from the list while its tab is open: the list is fetched again.
    const calls = () => fetchMock.mock.calls.filter(([path]) => path === "/api/vms").length;
    const before = calls();
    act(() => socket.push({ type: "vm.removed", uuid: "2" }));
    await vi.waitFor(() => expect(calls()).toBeGreaterThan(before));
  });
});
