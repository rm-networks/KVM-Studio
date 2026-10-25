import type { Snapshot } from "../../api/client";

export interface Row {
  snap: Snapshot;
  depth: number;
}

/** Snapshots in tree order: each one followed by its children, oldest first. */
export function treeRows(snaps: Snapshot[]): Row[] {
  const rows: Row[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const snap of snaps.filter((s) => s.parent === parent)) {
      rows.push({ snap, depth });
      walk(snap.name, depth + 1);
    }
  };
  walk(null, 0);
  return rows;
}
