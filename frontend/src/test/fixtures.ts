import type { VmSummary } from "../api/client";

export function makeVm(overrides: Partial<VmSummary> & { name: string }): VmSummary {
  return {
    uuid: overrides.name,
    state: "shutoff",
    vcpus: 2,
    memory_mib: 2048,
    persistent: true,
    folder: "",
    managed: true,
    drift: [],
    ...overrides,
  };
}
