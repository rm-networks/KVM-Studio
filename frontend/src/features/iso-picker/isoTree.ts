import type { IsoFile } from "../../api/client";

export interface IsoFolder {
  id: string; // "<library>/<relative folder>"
  name: string;
  library: string;
  folders: IsoFolder[];
  files: IsoFile[];
}

export type IsoSort = "name" | "size" | "date";

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

export function fileName(iso: IsoFile): string {
  return iso.relative.slice(iso.relative.lastIndexOf("/") + 1);
}

/** One root per library, then its folders, with the ISO files of each folder. */
export function buildIsoTree(libraries: string[], isos: IsoFile[]): IsoFolder[] {
  const nodes = new Map<string, IsoFolder>();
  const roots: IsoFolder[] = libraries.map((library) => {
    const root: IsoFolder = { id: `${library}/`, name: library, library, folders: [], files: [] };
    nodes.set(root.id, root);
    return root;
  });
  const folder = (library: string, path: string): IsoFolder => {
    const id = `${library}/${path}`;
    let found = nodes.get(id);
    if (!found) {
      const cut = path.lastIndexOf("/");
      const parent = folder(library, cut === -1 ? "" : path.slice(0, cut));
      found = { id, name: path.slice(cut + 1), library, folders: [], files: [] };
      parent.folders.push(found);
      nodes.set(id, found);
    }
    return found;
  };
  for (const iso of isos) {
    const cut = iso.relative.lastIndexOf("/");
    folder(iso.library, cut === -1 ? "" : iso.relative.slice(0, cut)).files.push(iso);
  }
  const sortFolders = (n: IsoFolder) => {
    n.folders.sort((a, b) => collator.compare(a.name, b.name));
    n.folders.forEach(sortFolders);
  };
  roots.forEach(sortFolders);
  return roots;
}

export function sortIsos(files: IsoFile[], sort: IsoSort, descending: boolean): IsoFile[] {
  const sign = descending ? -1 : 1;
  return [...files].sort((a, b) => {
    const diff =
      sort === "size"
        ? a.size - b.size
        : sort === "date"
          ? a.mtime - b.mtime
          : collator.compare(fileName(a), fileName(b));
    return sign * (diff || collator.compare(fileName(a), fileName(b)));
  });
}

function normalize(text: string): string {
  return text
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .toLowerCase();
}

export function searchIsos(isos: IsoFile[], query: string): IsoFile[] {
  const needle = normalize(query.trim());
  return needle ? isos.filter((iso) => normalize(iso.relative).includes(needle)) : isos;
}

export function formatSize(bytes: number, units: [string, string, string]): string {
  const [mb, gb, kb] = units;
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} ${gb}`;
  if (bytes >= 1024 ** 2) return `${Math.round(bytes / 1024 ** 2)} ${mb}`;
  return `${Math.max(1, Math.round(bytes / 1024))} ${kb}`;
}
