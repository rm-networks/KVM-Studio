import {
  ChevronDown,
  ChevronRight,
  CircleCheck,
  Disc3,
  Folder,
  Library,
  Search,
  TriangleAlert,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type AccessReport, type IsoFile, type IsoListing } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { useNotifier } from "../../components/notifier";
import {
  buildIsoTree,
  fileName,
  formatSize,
  type IsoFolder,
  type IsoSort,
  searchIsos,
  sortIsos,
} from "./isoTree";
import "./IsoPicker.css";

interface Props {
  title?: string;
  onPick: (path: string) => void;
  onClose: () => void;
}

function FolderRow({
  folder,
  depth,
  selected,
  expanded,
  onSelect,
  onToggle,
}: {
  folder: IsoFolder;
  depth: number;
  selected: string;
  expanded: ReadonlySet<string>;
  onSelect: (id: string) => void;
  onToggle: (id: string) => void;
}) {
  const open = expanded.has(folder.id);
  const isRoot = depth === 0;
  return (
    <>
      <li
        role="treeitem"
        aria-selected={selected === folder.id}
        aria-expanded={folder.folders.length > 0 ? open : undefined}
        className="list-row"
        style={{ paddingLeft: 4 + depth * 16 }}
        onClick={() => onSelect(folder.id)}
        onDoubleClick={() => onToggle(folder.id)}
      >
        <span
          className="iso-twisty"
          onClick={(e) => {
            e.stopPropagation();
            onToggle(folder.id);
          }}
        >
          {folder.folders.length > 0 && (open ? <ChevronDown /> : <ChevronRight />)}
        </span>
        {isRoot ? <Library aria-hidden /> : <Folder aria-hidden />}
        <span className="iso-label">{folder.name}</span>
      </li>
      {open &&
        folder.folders.map((child) => (
          <FolderRow
            key={child.id}
            folder={child}
            depth={depth + 1}
            selected={selected}
            expanded={expanded}
            onSelect={onSelect}
            onToggle={onToggle}
          />
        ))}
    </>
  );
}

function findFolder(roots: IsoFolder[], id: string): IsoFolder | undefined {
  for (const root of roots) {
    if (root.id === id) return root;
    const found = findFolder(root.folders, id);
    if (found) return found;
  }
  return undefined;
}

export function IsoPicker({ title, onPick, onClose }: Props) {
  const { t, i18n } = useTranslation();
  const { notifyError } = useNotifier();
  const [listing, setListing] = useState<IsoListing | null>(null);
  const [folderId, setFolderId] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<IsoSort>("name");
  const [descending, setDescending] = useState(false);
  const [picked, setPicked] = useState<IsoFile | null>(null);
  const [report, setReport] = useState<AccessReport | null>(null);
  const [fixing, setFixing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .isos()
      .then((data) => {
        if (cancelled) return;
        setListing(data);
        const first = data.libraries[0];
        if (first) {
          setFolderId(`${first.name}/`);
          setExpanded(new Set(data.libraries.map((l) => `${l.name}/`)));
        }
      })
      .catch((err: unknown) => !cancelled && notifyError(t("iso.title"), err));
    return () => {
      cancelled = true;
    };
  }, [notifyError, t]);

  useEffect(() => {
    if (!picked) return;
    let cancelled = false;
    api
      .isoAccess(picked.path)
      .then((r) => !cancelled && setReport(r))
      .catch(() => !cancelled && setReport(null));
    return () => {
      cancelled = true;
    };
  }, [picked]);

  const roots = useMemo(
    () =>
      listing
        ? buildIsoTree(
            listing.libraries.map((l) => l.name),
            listing.isos,
          )
        : [],
    [listing],
  );
  const searching = query.trim() !== "";
  const shown = useMemo(() => {
    const base = searching
      ? searchIsos(listing?.isos ?? [], query)
      : (findFolder(roots, folderId)?.files ?? []);
    return sortIsos(base, sort, descending);
  }, [searching, listing, query, roots, folderId, sort, descending]);

  const units: [string, string, string] = [t("units.mb"), t("units.gb"), t("units.kb")];
  const dateFormat = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "short",
    timeStyle: "short",
  });

  const header = (key: IsoSort, label: string) => (
    <th
      aria-sort={sort === key ? (descending ? "descending" : "ascending") : "none"}
      onClick={() => {
        if (sort === key) setDescending((d) => !d);
        else {
          setSort(key);
          setDescending(key !== "name");
        }
      }}
    >
      {label}
      {sort === key && (descending ? " ▾" : " ▴")}
    </th>
  );

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const unavailable = listing?.libraries.filter((l) => !l.available) ?? [];

  return (
    <Dialog
      open
      width={820}
      onOpenChange={(open) => !open && onClose()}
      title={title ?? t("iso.title")}
      buttons={
        <>
          <button
            type="button"
            className="button button-primary"
            disabled={!picked}
            onClick={() => picked && onPick(picked.path)}
          >
            {t("iso.choose")}
          </button>
          <button type="button" className="button" onClick={onClose}>
            {t("common.cancel")}
          </button>
        </>
      }
    >
      <div className="iso-search">
        <Search aria-hidden />
        <input
          type="search"
          value={query}
          placeholder={t("iso.search")}
          aria-label={t("iso.search")}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      {listing && listing.libraries.length === 0 ? (
        <p className="iso-empty">{t("iso.noLibrary")}</p>
      ) : (
        <div className="iso-body">
          <ul className="list iso-tree" role="tree" aria-label={t("iso.libraries")}>
            {roots.map((root) => (
              <FolderRow
                key={root.id}
                folder={root}
                depth={0}
                selected={searching ? "" : folderId}
                expanded={expanded}
                onSelect={(id) => {
                  setQuery("");
                  setFolderId(id);
                }}
                onToggle={toggle}
              />
            ))}
          </ul>
          <div className="list iso-files">
            <table className="table">
              <thead>
                <tr>
                  {header("name", t("iso.name"))}
                  {header("size", t("iso.size"))}
                  {header("date", t("iso.modified"))}
                </tr>
              </thead>
              <tbody>
                {shown.map((file) => (
                  <tr
                    key={file.path}
                    aria-selected={picked?.path === file.path}
                    className={picked?.path === file.path ? "selected" : undefined}
                    title={file.path}
                    onClick={() => {
                      setReport(null);
                      setPicked(file);
                    }}
                    onDoubleClick={() => onPick(file.path)}
                  >
                    <td>
                      <span className="iso-name">
                        <Disc3 aria-hidden />
                        {searching ? file.relative : fileName(file)}
                      </span>
                    </td>
                    <td className="iso-num">{formatSize(file.size, units)}</td>
                    <td className="iso-num">{dateFormat.format(new Date(file.mtime * 1000))}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {listing && shown.length === 0 && (
              <p className="iso-empty">{searching ? t("library.noMatch") : t("iso.noFile")}</p>
            )}
          </div>
        </div>
      )}
      {unavailable.length > 0 && (
        <p className="note note-warn iso-note">
          <TriangleAlert aria-hidden />
          {t("iso.unavailable", {
            names: unavailable.map((l) => `${l.name} (${l.path})`).join(", "),
          })}
        </p>
      )}
      {picked && report && (
        <div className={report.readable ? "note iso-note" : "note note-error iso-note"}>
          {report.readable ? (
            <p>
              <CircleCheck aria-hidden /> {t("iso.readable")}
            </p>
          ) : (
            <>
              <p>
                <TriangleAlert aria-hidden />{" "}
                {t("iso.notReadable", { who: report.identity ?? "QEMU" })}
              </p>
              <ul>
                {report.problems.map((p) => (
                  <li key={`${p.kind}:${p.path}`}>
                    {t(`iso.problem.${p.kind}`, { path: p.path })}
                  </li>
                ))}
              </ul>
              {report.commands.length > 0 && (
                <>
                  <p>
                    <button
                      type="button"
                      className="button"
                      disabled={fixing}
                      onClick={() => {
                        setFixing(true);
                        api
                          .fixIsoAccess(report.path)
                          .then(setReport)
                          .catch((err: unknown) => notifyError(t("iso.fixFailed"), err))
                          .finally(() => setFixing(false));
                      }}
                    >
                      {t("iso.fix")}
                    </button>
                  </p>
                  <p>{t("iso.fixWithCommands")}</p>
                  <pre>{report.commands.map((c) => `sudo ${c}`).join("\n")}</pre>
                </>
              )}
            </>
          )}
        </div>
      )}
    </Dialog>
  );
}
