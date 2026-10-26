import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationProvider } from "../../components/Notifications";
import { ScanDialog } from "./ScanDialog";

const found = [
  {
    id: "/old/KVM-Studio/VM/Labs/Web",
    name: "Web",
    folder: "Labs",
    disks: ["/old/KVM-Studio/VM/Labs/Web/Web.qcow2"],
    definition: null,
    known: null,
    uefi: true,
  },
  {
    id: "/old/Known",
    name: "Known",
    folder: "",
    disks: ["/old/Known/known.qcow2"],
    definition: null,
    known: "Mine",
    uefi: false,
  },
];

afterEach(() => vi.unstubAllGlobals());

describe("ScanDialog", () => {
  it("imports what was picked, after listing the moves", async () => {
    const posts: [string, unknown][] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, init?: RequestInit) => {
        if (init?.method === "POST") posts.push([path, JSON.parse(init.body as string)]);
        const body = path.startsWith("/api/scan/plan")
          ? {
              moves: [
                ["/old/KVM-Studio/VM/Labs/Web/Web.qcow2", "/data/KVM-Studio/VM/Labs/Web/Web.qcow2"],
              ],
            }
          : path.startsWith("/api/scan/import")
            ? { imported: ["Web"], failed: [] }
            : found;
        return Promise.resolve(new Response(JSON.stringify(body)));
      }),
    );
    const onClose = vi.fn();
    render(
      <NotificationProvider>
        <ScanDialog start="/old" onClose={onClose} />
      </NotificationProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Rechercher" }));
    expect(await screen.findByText("Déjà dans libvirt sous le nom Mine")).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "Known" })).toHaveProperty("disabled", true);
    expect(screen.getByRole("checkbox", { name: "Web" })).toHaveProperty("checked", true);
    const modes = screen.getAllByRole("combobox", { name: "Fichiers" });
    fireEvent.change(modes[0] as HTMLElement, { target: { value: "move" } });
    fireEvent.click(screen.getByRole("button", { name: "Importer 1 VM" }));
    expect(
      await screen.findByText(
        "/old/KVM-Studio/VM/Labs/Web/Web.qcow2 → /data/KVM-Studio/VM/Labs/Web/Web.qcow2",
      ),
    ).toBeTruthy();
    expect(posts.map(([p]) => p)).toEqual(["/api/scan/plan"]);
    fireEvent.click(screen.getByRole("button", { name: "Importer" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(posts[1]).toEqual([
      "/api/scan/import",
      { path: "/old", choices: [{ id: "/old/KVM-Studio/VM/Labs/Web", mode: "move" }] },
    ]);
  });
});
