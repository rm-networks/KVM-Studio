import { describe, expect, it } from "vitest";

import { snapshotNameProblem } from "./snapshotName";

describe("snapshotNameProblem", () => {
  it("accepts what libvirt 12 takes on a running VM", () => {
    for (const name of ["Snapshot-1", "a.b_c-d", "1abc", "_x", "-x"]) {
      expect(snapshotNameProblem(name)).toBeNull();
    }
  });

  it("names the first character refused", () => {
    expect(snapshotNameProblem("Snapshot 1")).toEqual({ kind: "char", char: " " });
    expect(snapshotNameProblem("été")).toEqual({ kind: "char", char: "é" });
    expect(snapshotNameProblem("a:b")).toEqual({ kind: "char", char: ":" });
  });

  it("refuses a leading dot, an empty name and a long one", () => {
    expect(snapshotNameProblem(".x")).toEqual({ kind: "dot" });
    expect(snapshotNameProblem("")).toEqual({ kind: "empty" });
    expect(snapshotNameProblem("a".repeat(101))).toEqual({ kind: "long" });
  });
});
