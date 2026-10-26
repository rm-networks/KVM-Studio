/**
 * What QEMU and libvirt accept as a snapshot name. A running VM's snapshot
 * becomes a QEMU job named "internal-snapshot-save-<name>", and QEMU only
 * takes letters, digits, "-", "." and "_" in a job name; libvirt also
 * refuses a name that starts with a dot. Same rule as the backend.
 */
export const SNAPSHOT_NAME_MAX = 100;
const ALLOWED = /[A-Za-z0-9_.-]/;

export type SnapshotNameProblem =
  { kind: "empty" } | { kind: "long" } | { kind: "dot" } | { kind: "char"; char: string };

export function snapshotNameProblem(name: string): SnapshotNameProblem | null {
  if (name === "") return { kind: "empty" };
  for (const char of name) {
    if (!ALLOWED.test(char)) return { kind: "char", char };
  }
  if (name.startsWith(".")) return { kind: "dot" };
  if (name.length > SNAPSHOT_NAME_MAX) return { kind: "long" };
  return null;
}
