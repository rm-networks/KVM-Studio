import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { BrowseButton } from "../files/BrowseButton";

type Bus = "virtio" | "sata" | "scsi";

interface Props {
  uuid: string;
  /** False when the VM runs: SATA has no hotplug. */
  off: boolean;
  onAdd: (disk: { bus: Bus; size_gib: number; existing: string | null }) => void;
  onCancel: () => void;
}

export function AddDiskDialog({ uuid, off, onAdd, onCancel }: Props) {
  const { t } = useTranslation();
  const [source, setSource] = useState<"new" | "existing">("new");
  const [size, setSize] = useState(20);
  const [bus, setBus] = useState<Bus>("virtio");
  const [existing, setExisting] = useState("");
  const [folder, setFolder] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .disksFolder(uuid)
      .then((r) => !cancelled && setFolder(r.path))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [uuid]);

  const valid = source === "new" ? size >= 1 : existing.trim().startsWith("/");

  return (
    <Dialog
      open
      width={520}
      onOpenChange={(open) => !open && onCancel()}
      title={t("settings.addDiskTitle")}
      buttons={
        <>
          <button
            type="button"
            className="button button-primary"
            disabled={!valid}
            onClick={() =>
              onAdd({
                bus,
                size_gib: source === "new" ? size : 0,
                existing: source === "existing" ? existing.trim() : null,
              })
            }
          >
            {t("settings.addDiskOk")}
          </button>
          <button type="button" className="button" onClick={onCancel}>
            {t("common.cancel")}
          </button>
        </>
      }
    >
      <label className="check">
        <input type="radio" checked={source === "new"} onChange={() => setSource("new")} />
        {t("settings.diskNew")}
      </label>
      {source === "new" && (
        <div className="add-disk-indent">
          <label className="settings-inline">
            {t("settings.diskSize")}
            <input
              type="number"
              min={1}
              value={size}
              onChange={(e) => setSize(Number(e.target.value))}
            />
            {t("units.gibShort")}
          </label>
          {folder && (
            <p className="muted">
              {t("settings.diskWhere")} <span className="mono">{folder}</span>
            </p>
          )}
        </div>
      )}
      <label className="check">
        <input
          type="radio"
          checked={source === "existing"}
          onChange={() => setSource("existing")}
        />
        {t("settings.diskExisting")}
      </label>
      {source === "existing" && (
        <div className="add-disk-indent settings-row">
          <input
            type="text"
            className="mono"
            aria-label={t("settings.diskFile")}
            value={existing}
            onChange={(e) => setExisting(e.target.value)}
          />
          <BrowseButton
            kind="disk"
            start={existing || folder}
            title={t("settings.diskExisting")}
            onPick={setExisting}
          />
        </div>
      )}
      <label className="settings-inline">
        {t("settings.diskBus")}
        <select value={bus} onChange={(e) => setBus(e.target.value as Bus)}>
          {(["virtio", "scsi", "sata"] as const).map((b) => (
            <option key={b} value={b}>
              {t(`wizard.bus.${b}`)}
            </option>
          ))}
        </select>
      </label>
      {!off && bus === "sata" && <p className="muted">{t("settings.sataNeedsOff")}</p>}
    </Dialog>
  );
}
