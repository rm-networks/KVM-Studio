import type { VmSummary } from "../../api/client";
import { type VmFilter, type VmSort, visibleVms } from "./filter";

export interface FolderNode {
  path: string; // "" for My Computer
  name: string;
  folders: FolderNode[];
  vms: VmSummary[];
}

export const folderId = (path: string) => `f:${path}`;
export const vmId = (uuid: string) => `v:${uuid}`;
export const ROOT_ID = folderId("");

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

export function parentOf(path: string): string {
  const i = path.lastIndexOf("/");
  return i === -1 ? "" : path.slice(0, i);
}

/**
 * Folder tree with its VMs. While searching or filtering, folders without a
 * matching VM underneath are left out.
 */
export function buildTree(
  folders: string[],
  vms: VmSummary[],
  query: string,
  filter: VmFilter,
  sort: VmSort,
): FolderNode {
  const nodes = new Map<string, FolderNode>();
  const node = (path: string): FolderNode => {
    let found = nodes.get(path);
    if (!found) {
      found = { path, name: path.slice(path.lastIndexOf("/") + 1), folders: [], vms: [] };
      nodes.set(path, found);
      if (path !== "") node(parentOf(path)).folders.push(found);
    }
    return found;
  };
  node("");
  for (const path of folders) node(path);
  for (const vm of visibleVms(vms, query, filter, sort)) node(vm.folder).vms.push(vm);

  const narrowed = query.trim() !== "" || filter !== "all";
  const finish = (n: FolderNode): boolean => {
    n.folders = n.folders.filter(finish).sort((a, b) => collator.compare(a.name, b.name));
    return !narrowed || n.path === "" || n.vms.length > 0 || n.folders.length > 0;
  };
  const root = node("");
  finish(root);
  return root;
}

export interface Row {
  id: string;
  depth: number;
  folder?: FolderNode;
  vm?: VmSummary;
}

/** Rows in display order, honouring the expanded folders. */
export function visibleRows(
  root: FolderNode,
  expanded: ReadonlySet<string>,
  forceOpen: boolean,
): Row[] {
  const rows: Row[] = [];
  const walk = (n: FolderNode, depth: number) => {
    rows.push({ id: folderId(n.path), depth, folder: n });
    if (!forceOpen && !expanded.has(n.path)) return;
    for (const child of n.folders) walk(child, depth + 1);
    for (const vm of n.vms) rows.push({ id: vmId(vm.uuid), depth: depth + 1, vm });
  };
  walk(root, 0);
  return rows;
}
