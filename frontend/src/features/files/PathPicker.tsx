import { ArrowUp, Disc3, Folder, HardDrive, Home, Library } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, api, type FileListing } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { ErrorMessage } from "../../components/ErrorMessage";
import { formatSize } from "../iso-picker/isoTree";
import "./PathPicker.css";

export type PathKind = "disk" | "folder";

interface Props {
  kind: PathKind;
  title: string;
  start: string | null;
  onChoose: (path: string) => void;
  onClose: () => void;
}

const PLACE_ICONS = { home: Home, library: Library, iso: Disc3 } as const;

/** Browse button of a web browser: the backend lists the folders (api/files). */
export function PathPicker({ kind, title, start, onChoose, onClose }: Props) {
  const { t } = useTranslation();
  const [listing, setListing] = useState<FileListing | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const units: [string, string, string] = [t("units.mb"), t("units.gb"), t("units.kb")];

  const load = (path: string | null, fallback = false) => {
    api
      .listFiles(path, kind)
      .then((found) => {
        setListing(found);
        setError(null);
      })
      .catch((err: unknown) => {
        // A starting point that does not exist (yet): the first place instead.
        if (fallback && path !== null) load(null);
        else setError(err instanceof ApiError ? err : new ApiError(0, "http.error", String(err)));
      });
  };

  const open = (path: string | null) => {
    setSelected(null);
    load(path);
  };

  useEffect(() => {
    // A file path starts in its folder.
    load(start && kind === "disk" ? start.replace(/\/[^/]*$/, "") || "/" : start, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, from where it starts
  }, []);

  const chosen = kind === "folder" ? (selected ?? listing?.path ?? null) : selected;

  return (
    <Dialog
      open
      width={680}
      onOpenChange={(o) => !o && onClose()}
      title={title}
      buttons={
        <>
          <button
            type="button"
            className="button button-primary"
            disabled={!chosen}
            onClick={() => chosen && onChoose(chosen)}
          >
            {t("files.choose")}
          </button>
          <button type="button" className="button" onClick={onClose}>
            {t("common.cancel")}
          </button>
        </>
      }
    >
      <div className="path-bar">
        <button
          type="button"
          className="icon-button"
          aria-label={t("files.up")}
          title={t("files.up")}
          disabled={!listing?.parent}
          onClick={() => listing?.parent && open(listing.parent)}
        >
          <ArrowUp aria-hidden />
        </button>
        <span className="path-current mono">{listing?.path ?? ""}</span>
      </div>
      <div className="path-body">
        <ul className="list path-places" aria-label={t("files.places")}>
          {listing?.places.map((place) => {
            const Icon = PLACE_ICONS[place.kind as keyof typeof PLACE_ICONS] ?? Folder;
            return (
              <li
                key={place.path}
                className="list-row"
                aria-selected={listing.path === place.path}
                title={place.path}
                onClick={() => open(place.path)}
              >
                <Icon aria-hidden />
                {t(`files.place.${place.kind}`)}
              </li>
            );
          })}
        </ul>
        <div className="list path-entries">
          {error && <ErrorMessage error={error} />}
          {listing && listing.entries.length === 0 && (
            <p className="path-empty">{t(kind === "disk" ? "files.noDisk" : "files.noFolder")}</p>
          )}
          <ul role="listbox" aria-label={listing?.path ?? ""}>
            {listing?.entries.map((entry) => {
              const Icon = entry.folder ? Folder : HardDrive;
              return (
                <li
                  key={entry.path}
                  role="option"
                  className="list-row"
                  aria-selected={selected === entry.path}
                  onClick={() =>
                    entry.folder && kind === "disk" ? open(entry.path) : setSelected(entry.path)
                  }
                  onDoubleClick={() => (entry.folder ? open(entry.path) : onChoose(entry.path))}
                >
                  <Icon aria-hidden />
                  <span className="path-name">{entry.name}</span>
                  {!entry.folder && (
                    <span className="path-size">{formatSize(entry.size, units)}</span>
                  )}
                </li>
              );
            })}
          </ul>
          {listing?.truncated && <p className="path-empty">{t("files.truncated")}</p>}
        </div>
      </div>
    </Dialog>
  );
}
