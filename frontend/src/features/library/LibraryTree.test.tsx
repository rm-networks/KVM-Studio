import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import type { VmSummary } from "../../api/client";
import { NotificationProvider } from "../../components/Notifications";
import { makeVm } from "../../test/fixtures";
import { VmActionsProvider } from "../vm/VmActions";
import { LibraryActionsProvider } from "./LibraryActions";
import { LibraryTree } from "./LibraryTree";
import { buildTree, ROOT_ID } from "./tree";

interface HarnessProps {
  vms: VmSummary[];
  folders?: string[];
  onOpen?: (uuid: string) => void;
}

function Harness({ vms, folders = [], onOpen = () => undefined }: HarnessProps) {
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <NotificationProvider>
      <VmActionsProvider>
        <LibraryActionsProvider library={{ root: "/data/KVM-Studio/VM", folders }}>
          <LibraryTree
            root={buildTree(folders, vms, "", "all", "name")}
            selected={selected}
            onSelect={setSelected}
            onOpen={onOpen}
            forceOpen={false}
            vmsByUuid={new Map(vms.map((v) => [v.uuid, v]))}
          />
        </LibraryActionsProvider>
      </VmActionsProvider>
    </NotificationProvider>
  );
}

const labels = () => screen.getAllByRole("treeitem").map((el) => el.textContent);

describe("LibraryTree", () => {
  it("shows folders before VMs under My Computer", () => {
    render(
      <Harness
        vms={[makeVm({ name: "win-10" }), makeVm({ name: "srv", folder: "Labs" })]}
        folders={["Labs"]}
      />,
    );
    expect(labels()).toEqual(["Mon ordinateur", "Labs", "win-10"]);
  });

  it("marks running VMs and files moved by hand", () => {
    render(
      <Harness
        vms={[
          makeVm({ name: "fw", state: "running" }),
          makeVm({ name: "lost", drift: ["missing_files"] }),
        ]}
      />,
    );
    expect(screen.getAllByRole("img", { name: "Allumée" })).toHaveLength(1);
    expect(screen.getByRole("img", { name: /introuvables/ })).toBeTruthy();
  });

  it("shows an empty state", () => {
    render(<Harness vms={[]} />);
    expect(screen.getByText("Aucune machine virtuelle")).toBeTruthy();
  });

  it("is usable with the keyboard, folders included", () => {
    render(
      <Harness
        vms={[makeVm({ name: "a" }), makeVm({ name: "b", folder: "Labs" })]}
        folders={["Labs"]}
      />,
    );
    const tree = screen.getByRole("tree");
    const active = () => tree.getAttribute("aria-activedescendant");
    expect(active()).toBe(`tree-${ROOT_ID}`);

    fireEvent.keyDown(tree, { key: "ArrowDown" });
    expect(active()).toBe("tree-f:Labs");
    expect(screen.queryByText("b")).toBeNull();
    fireEvent.keyDown(tree, { key: "ArrowRight" });
    expect(screen.getByText("b")).toBeTruthy();
    fireEvent.keyDown(tree, { key: "ArrowRight" });
    expect(active()).toBe("tree-v:b");
    fireEvent.keyDown(tree, { key: "ArrowLeft" });
    expect(active()).toBe("tree-f:Labs");
    fireEvent.keyDown(tree, { key: "End" });
    expect(active()).toBe("tree-v:a");
    fireEvent.keyDown(tree, { key: "Home" });
    fireEvent.keyDown(tree, { key: "ArrowLeft" });
    expect(screen.queryByText("a")).toBeNull();
  });

  it("opens a VM with Enter or a single click", () => {
    const opened: string[] = [];
    render(
      <Harness
        vms={[makeVm({ name: "a" }), makeVm({ name: "b" })]}
        onOpen={(uuid) => opened.push(uuid)}
      />,
    );
    const tree = screen.getByRole("tree");
    fireEvent.keyDown(tree, { key: "ArrowDown" });
    fireEvent.keyDown(tree, { key: "Enter" });
    fireEvent.click(screen.getByText("b"));
    expect(opened).toEqual(["a", "b"]);
  });
});
