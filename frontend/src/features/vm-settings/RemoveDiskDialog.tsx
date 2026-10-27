import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type DiskSize } from "../../api/client";
import { Dialog } from "../../components/Dialog";

interface Props {
  uuid: string;
  target: string;
  onRemove: (deleteFile: boolean) => void;
  onCancel: () => void;
}

/** The file stays unless asked; then exactly this file goes, nothing else. */
export function RemoveDiskDialog({ uuid, target, onRemove, onCancel }: Props) {
  const { t } = useTranslation();
  const [disk, setDisk] = useState<DiskSize | null>(null);
  const [deleteFile, setDeleteFile] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .diskSize(uuid, target)
      .then((d) => !cancelled && setDisk(d))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [uuid, target]);

  return (
    <Dialog
      open
      width={520}
      onOpenChange={(open) => !open && onCancel()}
      title={t("settings.remove")}
      buttons={
        <>
          <button
            type="button"
            className={deleteFile ? "button button-danger" : "button button-primary"}
            onClick={() => onRemove(deleteFile)}
          >
            {t("settings.remove")}
          </button>
          <button type="button" className="button" onClick={onCancel}>
            {t("common.cancel")}
          </button>
        </>
      }
    >
      <p>{t("settings.confirmRemoveDisk")}</p>
      {disk?.deletable && (
        <>
          <label className="check">
            <input
              type="checkbox"
              checked={deleteFile}
              onChange={(e) => setDeleteFile(e.target.checked)}
            />
            {t("settings.deleteDiskFile")}
          </label>
          <ul className="add-disk-indent mono">
            <li>{disk.path}</li>
          </ul>
        </>
      )}
      {disk && !disk.deletable && <p className="muted">{t("settings.diskFileKept")}</p>}
    </Dialog>
  );
}
