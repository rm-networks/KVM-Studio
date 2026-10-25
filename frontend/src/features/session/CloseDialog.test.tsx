import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationProvider } from "../../components/Notifications";
import { CloseDialog } from "./CloseDialog";

function mockApi(onClose: string, running: string[], reminder = true) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  const config = { workspace: { on_close: onClose, close_reminder: reminder } };
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push({ method, path, body: init?.body ? JSON.parse(init.body as string) : null });
      let body: unknown = { done: running, failed: [] };
      if (path === "/api/session/running") body = running.map((name) => ({ uuid: name, name }));
      if (path === "/api/preferences" && method === "GET") body = { config };
      if (path === "/api/preferences" && method === "PUT") body = { restart_required: false };
      return Promise.resolve(new Response(JSON.stringify(body)));
    }),
  );
  return calls;
}

function open(onProceed = vi.fn(), onCancel = vi.fn()) {
  render(
    <NotificationProvider>
      <CloseDialog reason="quit" onProceed={onProceed} onCancel={onCancel} />
    </NotificationProvider>,
  );
  return { onProceed, onCancel };
}

afterEach(() => vi.unstubAllGlobals());

describe("CloseDialog", () => {
  it("closes at once when no VM runs", async () => {
    mockApi("keep", []);
    const { onProceed } = open();
    await waitFor(() => expect(onProceed).toHaveBeenCalled());
  });

  it("reminds that VMs keep running, and can stop reminding", async () => {
    const calls = mockApi("keep", ["fw", "srv"]);
    const { onProceed } = open();
    expect(
      await screen.findByText("Ces 2 machines virtuelles sont encore allumées :"),
    ).toBeTruthy();
    expect(screen.getByText("fw")).toBeTruthy();
    fireEvent.click(screen.getByLabelText("Ne plus afficher"));
    fireEvent.click(screen.getByRole("button", { name: "Quitter" }));
    expect(onProceed).toHaveBeenCalled();
    await waitFor(() => expect(calls.at(-1)?.method).toBe("PUT"));
    expect(calls.at(-1)?.body).toEqual({ workspace: { on_close: "keep", close_reminder: false } });
  });

  it("asks, then suspends", async () => {
    const calls = mockApi("ask", ["fw"]);
    const { onProceed } = open();
    fireEvent.click(await screen.findByRole("button", { name: "Les suspendre" }));
    await waitFor(() => expect(onProceed).toHaveBeenCalled());
    expect(calls.some((c) => c.path === "/api/session/running/suspend")).toBe(true);
  });

  it("shuts down by itself when asked to in Preferences", async () => {
    const calls = mockApi("shutdown", ["fw"]);
    open();
    expect(await screen.findByText(/Arrêt des machines virtuelles/)).toBeTruthy();
    expect(calls.some((c) => c.path === "/api/session/running/shutdown")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Annuler" }));
  });
});
