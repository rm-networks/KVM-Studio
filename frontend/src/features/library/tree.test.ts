import { describe, expect, it } from "vitest";

import type { VmSummary } from "../../api/client";
import { buildTree, parentOf, visibleRows } from "./tree";

function vm(name: string, folder = "", state: VmSummary["state"] = "shutoff"): VmSummary {
  return {
    uuid: name,
    name,
    state,
    vcpus: 1,
    memory_mib: 512,
    persistent: true,
    folder,
    managed: true,
    drift: [],
  };
}

const vms = [vm("CentOS9", "Masters"), vm("SRV-WS22", "Labs/Réseau", "running"), vm("loose")];
const folders = ["Masters", "Labs", "Labs/Réseau", "Empty"];

describe("buildTree", () => {
  it("nests folders and places each VM in its folder", () => {
    const root = buildTree(folders, vms, "", "all", "name");
    expect(root.folders.map((f) => f.name)).toEqual(["Empty", "Labs", "Masters"]);
    expect(root.vms.map((v) => v.name)).toEqual(["loose"]);
    const labs = root.folders[1];
    expect(labs?.folders[0]?.path).toBe("Labs/Réseau");
    expect(labs?.folders[0]?.vms.map((v) => v.name)).toEqual(["SRV-WS22"]);
  });

  it("creates a folder that only exists in a VM note", () => {
    const root = buildTree([], [vm("x", "Virtual/Deep")], "", "all", "name");
    expect(root.folders[0]?.path).toBe("Virtual");
    expect(root.folders[0]?.folders[0]?.vms[0]?.name).toBe("x");
  });

  it("hides folders without matches while searching", () => {
    const root = buildTree(folders, vms, "ws22", "all", "name");
    expect(root.folders.map((f) => f.name)).toEqual(["Labs"]);
    expect(root.vms).toEqual([]);
    const running = buildTree(folders, vms, "", "running", "name");
    expect(running.folders.map((f) => f.name)).toEqual(["Labs"]);
  });
});

describe("visibleRows", () => {
  it("follows the expanded folders", () => {
    const root = buildTree(folders, vms, "", "all", "name");
    const ids = (expanded: string[], force = false) =>
      visibleRows(root, new Set(expanded), force).map((r) => r.id);
    expect(ids([""])).toEqual(["f:", "f:Empty", "f:Labs", "f:Masters", "v:loose"]);
    expect(ids(["", "Labs"])).toEqual([
      "f:",
      "f:Empty",
      "f:Labs",
      "f:Labs/Réseau",
      "f:Masters",
      "v:loose",
    ]);
    expect(ids([], true)).toContain("v:SRV-WS22");
  });
});

describe("parentOf", () => {
  it("returns the parent folder", () => {
    expect(parentOf("a/b/c")).toBe("a/b");
    expect(parentOf("a")).toBe("");
  });
});
