import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationProvider } from "../../components/Notifications";
import { DiskPanel } from "./DiskPanel";

const GIB = 1024 ** 3;
const disk = {
  target: "vda",
  bus: "virtio",
  path: "/vms/FW/FW.qcow2",
  device: "disk",
  format: "qcow2",
};

afterEach(() => vi.unstubAllGlobals());

describe("DiskPanel", () => {
  it("expands a disk to a larger size only", async () => {
    let capacity = 20 * GIB;
    const posted: unknown[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((_path: string, init?: RequestInit) => {
        if (init?.method === "POST") {
          posted.push(JSON.parse(init.body as string));
          capacity = 30 * GIB;
        }
        return Promise.resolve(
          new Response(
            JSON.stringify({ ...disk, capacity, allocation: 3 * GIB, expandable: true }),
          ),
        );
      }),
    );
    render(
      <NotificationProvider>
        <DiskPanel uuid="u1" disk={disk} />
      </NotificationProvider>,
    );
    expect(await screen.findByText("Taille : 20 Gio, 3 Gio occupés sur l'hôte")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Agrandir…" }));
    const field = screen.getByLabelText("Nouvelle taille (Gio)");
    fireEvent.change(field, { target: { value: "10" } });
    expect(screen.getByText("Plus grande que 20 Gio")).toBeTruthy();
    fireEvent.change(field, { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Agrandir" }));
    await waitFor(() => expect(posted).toEqual([{ gib: 30 }]));
    expect(await screen.findByText("Taille : 30 Gio, 3 Gio occupés sur l'hôte")).toBeTruthy();
  });
});
