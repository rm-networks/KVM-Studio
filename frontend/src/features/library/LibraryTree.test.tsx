import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import type { VmSummary } from "../../api/client";
import { LibraryTree, ROOT_ID } from "./LibraryTree";

function vm(name: string, state: VmSummary["state"] = "shutoff"): VmSummary {
  return { uuid: `uuid-${name}`, name, state, vcpus: 2, memory_mib: 2048, persistent: true };
}

function Harness({ vms }: { vms: VmSummary[] }) {
  const [selected, setSelected] = useState<string | null>(null);
  return <LibraryTree vms={vms} selected={selected} onSelect={setSelected} />;
}

const labels = () =>
  screen
    .getAllByRole("treeitem")
    .slice(1)
    .map((el) => el.textContent);

describe("LibraryTree", () => {
  it("sorts VMs naturally under My Computer", () => {
    render(<Harness vms={[vm("win-10"), vm("Debian"), vm("win-2"), vm("alpine")]} />);
    expect(screen.getByText("Mon ordinateur")).toBeTruthy();
    expect(labels()).toEqual(["alpine", "Debian", "win-2", "win-10"]);
  });

  it("marks running VMs", () => {
    render(<Harness vms={[vm("fw", "running"), vm("client")]} />);
    expect(screen.getAllByRole("img", { name: "Allumée" })).toHaveLength(1);
  });

  it("shows an empty state", () => {
    render(<Harness vms={[]} />);
    expect(screen.getByText("Aucune machine virtuelle")).toBeTruthy();
  });

  it("is usable with the keyboard", () => {
    render(<Harness vms={[vm("a"), vm("b")]} />);
    const tree = screen.getByRole("tree");
    expect(tree.getAttribute("aria-activedescendant")).toBe(`tree-${ROOT_ID}`);

    fireEvent.keyDown(tree, { key: "ArrowDown" });
    expect(tree.getAttribute("aria-activedescendant")).toBe("tree-uuid-a");
    fireEvent.keyDown(tree, { key: "End" });
    expect(tree.getAttribute("aria-activedescendant")).toBe("tree-uuid-b");
    fireEvent.keyDown(tree, { key: "ArrowLeft" });
    expect(tree.getAttribute("aria-activedescendant")).toBe(`tree-${ROOT_ID}`);

    fireEvent.keyDown(tree, { key: "ArrowLeft" });
    expect(screen.queryByText("a")).toBeNull();
    fireEvent.keyDown(tree, { key: "ArrowRight" });
    expect(screen.getByText("a")).toBeTruthy();
  });
});
