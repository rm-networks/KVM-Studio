import { describe, expect, it } from "vitest";

import type { VmSummary } from "../../api/client";
import { visibleVms } from "./filter";

function vm(name: string, state: VmSummary["state"] = "shutoff"): VmSummary {
  return { uuid: name, name, state, vcpus: 1, memory_mib: 512, persistent: true };
}

const vms = [vm("win-10"), vm("Debian", "running"), vm("win-2", "paused"), vm("Élysée", "running")];
const names = (list: VmSummary[]) => list.map((v) => v.name);

describe("visibleVms", () => {
  it("sorts by name, numbers in natural order", () => {
    expect(names(visibleVms(vms, "", "all", "name"))).toEqual([
      "Debian",
      "Élysée",
      "win-2",
      "win-10",
    ]);
  });

  it("sorts by state, then by name", () => {
    expect(names(visibleVms(vms, "", "all", "state"))).toEqual([
      "Debian",
      "Élysée",
      "win-2",
      "win-10",
    ]);
    expect(names(visibleVms([vm("b"), vm("a", "paused")], "", "all", "state"))).toEqual(["a", "b"]);
  });

  it("keeps only running machines", () => {
    expect(names(visibleVms(vms, "", "running", "name"))).toEqual(["Debian", "Élysée"]);
  });

  it("searches without case or accents", () => {
    expect(names(visibleVms(vms, "ELYSEE", "all", "name"))).toEqual(["Élysée"]);
    expect(names(visibleVms(vms, " win ", "all", "name"))).toEqual(["win-2", "win-10"]);
  });
});
