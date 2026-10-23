import type { VmState, VmSummary } from "../../api/client";

export type VmFilter = "all" | "running";
export type VmSort = "name" | "state";

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

// Live machines first, the way an admin scans the list.
const STATE_ORDER: Record<VmState, number> = {
  running: 0,
  paused: 1,
  suspended: 2,
  shutting_down: 3,
  crashed: 4,
  shutoff: 5,
  unknown: 6,
};

function normalize(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();
}

export function visibleVms(
  vms: VmSummary[],
  query: string,
  filter: VmFilter,
  sort: VmSort,
): VmSummary[] {
  const needle = normalize(query.trim());
  const byName = (a: VmSummary, b: VmSummary) => collator.compare(a.name, b.name);
  return vms
    .filter((vm) => filter === "all" || vm.state === "running")
    .filter((vm) => !needle || normalize(vm.name).includes(needle))
    .sort((a, b) =>
      sort === "state" ? STATE_ORDER[a.state] - STATE_ORDER[b.state] || byName(a, b) : byName(a, b),
    );
}
