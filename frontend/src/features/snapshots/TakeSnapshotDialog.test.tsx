import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SnapshotLimits } from "../../api/client";
import { makeVm } from "../../test/fixtures";
import { TakeSnapshotDialog } from "./TakeSnapshotDialog";

function limits(found: Partial<SnapshotLimits>) {
  const body = { running: false, raw_disks: [], raw_nvram: false, tpm: false, ...found };
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(new Response(JSON.stringify(body)))),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("TakeSnapshotDialog", () => {
  it("greys out the memory of a powered-off VM and tells about its TPM", async () => {
    limits({ tpm: true });
    const onTake = vi.fn();
    render(
      <TakeSnapshotDialog
        vm={makeVm({ name: "W11" })}
        existing={[]}
        onTake={onTake}
        onClose={vi.fn()}
      />,
    );
    await screen.findByText(/ne contient pas l.état de son TPM/);
    const memory = screen.getByRole("checkbox", { name: /Inclure la RAM/ }) as HTMLInputElement;
    expect([memory.checked, memory.disabled]).toEqual([false, true]);
    fireEvent.click(screen.getByRole("button", { name: "Prendre l'instantané" }));
    expect(onTake).toHaveBeenCalledWith("Instantané 1", "", false);
  });

  it("keeps the memory of a running VM unless told otherwise", async () => {
    limits({ running: true });
    const onTake = vi.fn();
    render(
      <TakeSnapshotDialog
        vm={makeVm({ name: "FW", state: "running" })}
        existing={[]}
        onTake={onTake}
        onClose={vi.fn()}
      />,
    );
    const memory = screen.getByRole("checkbox", { name: /Inclure la RAM/ }) as HTMLInputElement;
    expect([memory.checked, memory.disabled]).toEqual([true, false]);
    expect(memory.closest("label")?.getAttribute("title")).toMatch(/arrêt brutal/);
    fireEvent.click(memory);
    const take = screen.getByRole("button", { name: "Prendre l'instantané" }) as HTMLButtonElement;
    expect(take.disabled).toBe(true);
    expect(screen.getByText(/Éteignez la VM/)).toBeTruthy();
    fireEvent.click(memory);
    fireEvent.click(take);
    expect(onTake).toHaveBeenCalledWith("Instantané 1", "", true);
  });

  it("says beforehand what libvirt refuses", async () => {
    limits({ raw_disks: ["vda"], raw_nvram: true });
    render(
      <TakeSnapshotDialog
        vm={makeVm({ name: "OLD" })}
        existing={[]}
        onTake={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    await screen.findByText(/ces disques ne sont pas au format qcow2 : vda/);
    expect(screen.getByText(/variables UEFI/)).toBeTruthy();
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: "Prendre l'instantané" }) as HTMLButtonElement)
          .disabled,
      ).toBe(true),
    );
  });
});
