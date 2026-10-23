import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import type { VmSummary } from "../../api/client";
import { NotificationProvider } from "../../components/Notifications";
import { VmActionsProvider } from "../vm/VmActions";
import { LibraryTree, ROOT_ID } from "./LibraryTree";

function vm(name: string, state: VmSummary["state"] = "shutoff"): VmSummary {
  return { uuid: `uuid-${name}`, name, state, vcpus: 2, memory_mib: 2048, persistent: true };
}

function Harness({
  vms,
  onOpen = () => undefined,
}: {
  vms: VmSummary[];
  onOpen?: (uuid: string) => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <NotificationProvider>
      <VmActionsProvider>
        <LibraryTree vms={vms} selected={selected} onSelect={setSelected} onOpen={onOpen} />
      </VmActionsProvider>
    </NotificationProvider>
  );
}

const labels = () =>
  screen
    .getAllByRole("treeitem")
    .slice(1)
    .map((el) => el.textContent);

describe("LibraryTree", () => {
  it("lists VMs under My Computer in the given order", () => {
    render(<Harness vms={[vm("win-10"), vm("Debian"), vm("alpine")]} />);
    expect(screen.getByText("Mon ordinateur")).toBeTruthy();
    expect(labels()).toEqual(["win-10", "Debian", "alpine"]);
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

  it("opens a VM with Enter or a double click", () => {
    const opened: string[] = [];
    render(<Harness vms={[vm("a"), vm("b")]} onOpen={(uuid) => opened.push(uuid)} />);
    const tree = screen.getByRole("tree");
    fireEvent.keyDown(tree, { key: "ArrowDown" });
    fireEvent.keyDown(tree, { key: "Enter" });
    fireEvent.doubleClick(screen.getByText("b"));
    expect(opened).toEqual(["uuid-a", "uuid-b"]);
  });
});
