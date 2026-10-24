import { describe, expect, it } from "vitest";

import type { IsoFile } from "../../api/client";
import { buildIsoTree, formatSize, searchIsos, sortIsos } from "./isoTree";

function iso(relative: string, size = 1, mtime = 0, library = "ISO"): IsoFile {
  return { library, relative, path: `/srv/iso/${relative}`, size, mtime };
}

const files = [
  iso("debian-13.iso", 700 * 1024 ** 2, 3),
  iso("Windows/Win11_24H2.iso", 6 * 1024 ** 3, 1),
  iso("Windows/Server/SRV2025.iso", 5 * 1024 ** 3, 2),
  iso("Firewalls/OPNsense/opnsense.img", 2 * 1024 ** 2, 4),
];

describe("buildIsoTree", () => {
  it("nests folders under each library", () => {
    const [root] = buildIsoTree(["ISO", "Empty"], files);
    expect(root?.files.map((f) => f.relative)).toEqual(["debian-13.iso"]);
    expect(root?.folders.map((f) => f.name)).toEqual(["Firewalls", "Windows"]);
    const windows = root?.folders[1];
    expect(windows?.files.map((f) => f.relative)).toEqual(["Windows/Win11_24H2.iso"]);
    expect(windows?.folders[0]?.id).toBe("ISO/Windows/Server");
  });

  it("keeps empty libraries", () => {
    expect(buildIsoTree(["ISO", "Empty"], files)[1]?.files).toEqual([]);
  });
});

describe("sortIsos and searchIsos", () => {
  it("sorts by name, size or date", () => {
    const names = (list: IsoFile[]) => list.map((f) => f.relative.split("/").at(-1));
    expect(names(sortIsos(files, "name", false))).toEqual([
      "debian-13.iso",
      "opnsense.img",
      "SRV2025.iso",
      "Win11_24H2.iso",
    ]);
    expect(names(sortIsos(files, "size", true))[0]).toBe("Win11_24H2.iso");
    expect(names(sortIsos(files, "date", false))[0]).toBe("Win11_24H2.iso");
  });

  it("searches folder and file names", () => {
    expect(searchIsos(files, "server").map((f) => f.relative)).toEqual([
      "Windows/Server/SRV2025.iso",
    ]);
    expect(searchIsos(files, "  ")).toHaveLength(4);
  });

  it("formats sizes", () => {
    expect(formatSize(6 * 1024 ** 3, ["Mo", "Go", "Ko"])).toBe("6.0 Go");
    expect(formatSize(700 * 1024 ** 2, ["Mo", "Go", "Ko"])).toBe("700 Mo");
    expect(formatSize(10, ["Mo", "Go", "Ko"])).toBe("1 Ko");
  });
});
