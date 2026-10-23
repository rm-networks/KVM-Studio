import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { captureToken } from "../api/token";
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
  { uuid: "1", name: "FW-VYOS", state: "running", vcpus: 2, memory_mib: 1024, persistent: true },
  { uuid: "2", name: "CLT-DEB13", state: "shutoff", vcpus: 2, memory_mib: 2048, persistent: true },
];

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

describe("App", () => {
  it("sends the token from the URL and lists the VMs", async () => {
    window.history.replaceState(null, "", "/#token=abc123");
    captureToken();
    expect(window.location.hash).toBe("");

    const fetchMock = mockFetch((path) => [200, path === "/api/info" ? info : vms]);
    render(<App />);

    expect(await screen.findByText("FW-VYOS")).toBeTruthy();
    expect(screen.getByText("CLT-DEB13")).toBeTruthy();
    expect(screen.getByText("2 machines virtuelles, 1 allumée")).toBeTruthy();
    expect(screen.getByText("Connecté à qemu:///system")).toBeTruthy();

    const headers = fetchMock.mock.calls[0]?.[1]?.headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer abc123");
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
});
