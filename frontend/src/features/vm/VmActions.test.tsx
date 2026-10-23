import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { VmSummary } from "../../api/client";
import { NotificationProvider } from "../../components/Notifications";
import { powerAllowed } from "./power";
import { VmActionsProvider } from "./VmActions";
import { useVmActions } from "./vmActionsContext";

const off: VmSummary = {
  uuid: "u1",
  name: "SRV-WS22",
  state: "shutoff",
  vcpus: 2,
  memory_mib: 4096,
  persistent: true,
};
const on: VmSummary = { ...off, state: "running" };

type Call = { method: string; path: string; body?: string };

function mockFetch(responses: Record<string, [number, unknown]>) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push({ method, path, body: init?.body as string | undefined });
      const [status, body] = responses[`${method} ${path}`] ?? [204, null];
      return Promise.resolve(
        new Response(status === 204 ? null : JSON.stringify(body), { status }),
      );
    }),
  );
  return calls;
}

function Buttons({ vm }: { vm: VmSummary }) {
  const actions = useVmActions();
  return (
    <>
      <button onClick={() => actions.power(vm, "start")}>start</button>
      <button onClick={() => actions.power(vm, "poweroff")}>poweroff</button>
      <button onClick={() => actions.rename(vm)}>rename</button>
      <button onClick={() => actions.remove(vm, true)}>delete</button>
    </>
  );
}

function setup(vm: VmSummary) {
  render(
    <NotificationProvider>
      <VmActionsProvider>
        <Buttons vm={vm} />
      </VmActionsProvider>
    </NotificationProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("powerAllowed", () => {
  it("matches the VM state", () => {
    expect(powerAllowed("shutoff", "start")).toBe(true);
    expect(powerAllowed("shutoff", "shutdown")).toBe(false);
    expect(powerAllowed("running", "start")).toBe(false);
    expect(powerAllowed("running", "shutdown")).toBe(true);
    expect(powerAllowed("paused", "reset")).toBe(true);
    expect(powerAllowed("paused", "reboot")).toBe(false);
    expect(powerAllowed("crashed", "start")).toBe(true);
  });
});

describe("VM actions", () => {
  it("starts right away", async () => {
    const calls = mockFetch({});
    setup(off);
    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({ method: "POST", path: "/api/vms/u1/power/start" });
  });

  it("asks before forcing a power off", async () => {
    const calls = mockFetch({});
    setup(on);
    fireEvent.click(screen.getByText("poweroff"));
    expect(screen.getByText(/Les données non enregistrées/)).toBeTruthy();
    expect(calls).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Forcer l'arrêt" }));
    await waitFor(() => expect(calls[0]?.path).toBe("/api/vms/u1/power/poweroff"));
  });

  it("reports a failed action", async () => {
    mockFetch({
      "POST /api/vms/u1/power/start": [
        409,
        { error: { code: "libvirt.invalid_state", detail: "The virtual machine is running" } },
      ],
    });
    setup(off);
    fireEvent.click(screen.getByText("start"));
    expect(await screen.findByText("« Démarrer » a échoué pour SRV-WS22")).toBeTruthy();
    expect(screen.getByText("The virtual machine is running")).toBeTruthy();
  });

  it("renames with a valid name only", async () => {
    const calls = mockFetch({});
    setup(off);
    fireEvent.click(screen.getByText("rename"));
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "bad/name" } });
    expect(screen.getByText(/Nom invalide/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Renommer" }).hasAttribute("disabled")).toBe(true);
    fireEvent.change(input, { target: { value: "SRV-WS25" } });
    fireEvent.click(screen.getByRole("button", { name: "Renommer" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({ method: "PATCH", path: "/api/vms/u1" });
    expect(JSON.parse(calls[0]?.body ?? "{}")).toEqual({ name: "SRV-WS25" });
  });

  it("lists exactly what will be deleted before deleting", async () => {
    const calls = mockFetch({
      "GET /api/vms/u1/deletion-plan": [
        200,
        {
          delete: ["/data/KVM-Studio/VM/Labs/SRV-WS22/SRV-WS22.qcow2"],
          keep: [{ path: "/srv/iso/win.iso", reason: "iso" }],
        },
      ],
      "DELETE /api/vms/u1?files=true": [200, { deleted: [], failed: [], keep: [] }],
    });
    setup(off);
    fireEvent.click(screen.getByText("delete"));
    expect(
      await screen.findByText("/data/KVM-Studio/VM/Labs/SRV-WS22/SRV-WS22.qcow2"),
    ).toBeTruthy();
    expect(screen.getByText("1 fichier sera effacé")).toBeTruthy();
    expect(screen.getByText("image ISO")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Supprimer définitivement" }));
    await waitFor(() => expect(calls.at(-1)?.method).toBe("DELETE"));
    expect(calls.at(-1)?.path).toBe("/api/vms/u1?files=true");
  });

  it("refuses to delete a running VM", async () => {
    mockFetch({ "GET /api/vms/u1/deletion-plan": [200, { delete: [], keep: [] }] });
    setup(on);
    fireEvent.click(screen.getByText("delete"));
    expect(screen.getByText("Éteignez d'abord la machine virtuelle.")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: "Supprimer définitivement" }).hasAttribute("disabled"),
    ).toBe(true);
  });
});
