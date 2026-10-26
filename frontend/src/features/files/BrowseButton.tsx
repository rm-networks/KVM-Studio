import { useState } from "react";
import { useTranslation } from "react-i18next";

import { diskPicker, folderPicker } from "../../platform/folders";
import { PathPicker, type PathKind } from "./PathPicker";

interface Props {
  kind: PathKind;
  /** Where the picker opens: the current value, or null. */
  start: string | null;
  title: string;
  onPick: (path: string) => void;
}

/** "Browse…": the window's own dialog, or the backend's listing in a browser. */
export function BrowseButton({ kind, start, title, onPick }: Props) {
  const { t } = useTranslation();
  const [listing, setListing] = useState(false);
  const native = kind === "disk" ? diskPicker() : folderPicker();

  return (
    <>
      <button
        type="button"
        className="button"
        onClick={() => {
          if (native) void native(start).then((path) => path && onPick(path));
          else setListing(true);
        }}
      >
        {t("files.browse")}
      </button>
      {listing && (
        <PathPicker
          kind={kind}
          title={title}
          start={start}
          onChoose={(path) => {
            setListing(false);
            onPick(path);
          }}
          onClose={() => setListing(false)}
        />
      )}
    </>
  );
}
