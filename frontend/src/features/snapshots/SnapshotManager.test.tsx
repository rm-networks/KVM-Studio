import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationProvider } from "../../components/Notifications";
import { makeVm } from "../../test/fixtures";
import { SnapshotManager } from "./SnapshotManager";

const snaps = [
  {
    name: "Clean",
    description: "fresh install",
    created: 1,
    state: "shutoff",
    parent: null,
    current: false,
  },
  { name: "Tools", description: "", created: 2, state: "running", parent: "Clean", current: true },
  { name: "Other", description: "", created: 3, state: "shutoff", parent: "Clean", current: false },
];

afterEach(() => vi.unstubAllGlobals());

describe("SnapshotManager", () => {
  it("shows the tree with You are here, and asks before restoring", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, init?: RequestInit) => {
        calls.push(`${init?.method ?? "GET"} ${path}`);
        if (init?.method && init.method !== "GET")
          return Promise.resolve(new Response(null, { status: 204 }));
        return Promise.resolve(new Response(JSON.stringify(snaps)));
      }),
    );
    render(
      <NotificationProvider>
        <SnapshotManager vm={makeVm({ uuid: "u1", name: "FW" })} onClose={() => undefined} />
      </NotificationProvider>,
    );
    await screen.findByText("Clean");
    const rows = screen.getByRole("listbox").querySelectorAll("li");
    expect([...rows].map((r) => r.textContent)).toEqual([
      "Clean",
      "Tools",
      "Vous êtes ici",
      "Other",
    ]);
    fireEvent.click(screen.getByText("Clean"));
    expect(screen.getByText("fresh install")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Restaurer" }));
    expect(screen.getByText(/Tout ce qui a changé depuis/)).toBeTruthy();
    expect(calls.some((c) => c.startsWith("POST"))).toBe(false);
    fireEvent.click(screen.getAllByRole("button", { name: "Restaurer" }).at(-1) as HTMLElement);
    await waitFor(() => expect(calls).toContain("POST /api/vms/u1/snapshots/Clean/revert"));
  });
});
