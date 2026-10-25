import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

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
  onSettings?: (uuid: string) => void;
}

function Harness({
  vms,
  folders = [],
  onOpen = () => undefined,
  onSettings = () => undefined,
}: HarnessProps) {
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <NotificationProvider>
      <VmActionsProvider>
        <LibraryActionsProvider library={{ root: "/data/KVM-Studio/VM", folders, order: {} }}>
          <LibraryTree
            root={buildTree(folders, vms, "", "all", "name")}
            selected={selected}
            onSelect={setSelected}
            onOpen={onOpen}
            onSettings={onSettings}
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

  it("opens the settings from the context menu, last after Delete from disk", async () => {
    const settings: string[] = [];
    render(<Harness vms={[makeVm({ name: "a" })]} onSettings={(uuid) => settings.push(uuid)} />);
    fireEvent.contextMenu(screen.getByText("a"));
    const items = (await screen.findAllByRole("menuitem")).map((el) => el.textContent);
    expect(items[0]).toBe("Ouvrir dans un onglet");
    expect(items.slice(-2)).toEqual(["Supprimer du disque…", "Paramètres…Ctrl+D"]);
    const last = screen.getAllByRole("menuitem").at(-1) as HTMLElement;
    expect(last.previousElementSibling?.getAttribute("role")).toBe("separator");
    fireEvent.click(screen.getByRole("menuitem", { name: /Paramètres/ }));
    expect(settings).toEqual(["a"]);
  });

  it("moves a folder into another after showing what moves with it", async () => {
    const calls: { method: string; path: string; body: unknown }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((path: string, init?: RequestInit) => {
        const method = init?.method ?? "GET";
        calls.push({ method, path, body: init?.body ? JSON.parse(init.body as string) : null });
        const body = path.includes("move-plan")
          ? { folder: "Labs", target: "Archive/Labs", vms: ["R1"], running: [], blockers: [] }
          : { path: "Archive/Labs" };
        return Promise.resolve(new Response(JSON.stringify(body)));
      }),
    );
    render(
      <Harness vms={[makeVm({ name: "R1", folder: "Labs" })]} folders={["Labs", "Archive"]} />,
    );
    const types: string[] = [];
    const dataTransfer = {
      types,
      setData: (type: string) => types.push(type),
      getData: () => "",
      effectAllowed: "",
      dropEffect: "",
    };
    const row = (name: string) => screen.getByText(name).closest(".tree-row") as HTMLElement;
    fireEvent.dragStart(row("Labs"), { dataTransfer });
    fireEvent.dragOver(row("Archive"), { dataTransfer, clientY: 0.5 });
    fireEvent.drop(row("Archive"), { dataTransfer, clientY: 0.5 });

    expect(await screen.findByText("1 machine virtuelle le suit")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Déplacer" }));
    await vi.waitFor(() => expect(calls.at(-1)?.method).toBe("POST"));
    expect(calls.at(-1)).toEqual({
      method: "POST",
      path: "/api/library/folders/move",
      body: { path: "Labs", parent: "Archive", before: null },
    });
  });
});

afterEach(() => vi.unstubAllGlobals());
