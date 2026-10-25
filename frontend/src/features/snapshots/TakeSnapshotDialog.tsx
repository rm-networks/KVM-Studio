import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { VmSummary } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import "./SnapshotManager.css";

interface Props {
  vm: VmSummary;
  existing: string[];
  onTake: (name: string, description: string) => void;
  onClose: () => void;
}

/** Name and description of a new snapshot. */
export function TakeSnapshotDialog({ vm, existing, onTake, onClose }: Props) {
  const { t } = useTranslation();
  let n = existing.length + 1;
  while (existing.includes(t("snapshots.defaultName", { n }))) n += 1;
  const [name, setName] = useState(t("snapshots.defaultName", { n }));
  const [description, setDescription] = useState("");
  const taken = existing.includes(name.trim());
  const running = vm.state === "running" || vm.state === "paused";

  return (
    <Dialog
      open
      width={480}
      onOpenChange={(open) => !open && onClose()}
      title={t("snapshots.takeTitle", { name: vm.name })}
      buttons={
        <>
          <button
            type="button"
            className="button button-primary"
            disabled={!name.trim() || taken}
            onClick={() => {
              onTake(name.trim(), description);
              onClose();
            }}
          >
            {t("snapshots.takeButton")}
          </button>
          <button type="button" className="button" onClick={onClose}>
            {t("common.cancel")}
          </button>
        </>
      }
    >
      <p>{t(running ? "snapshots.takeRunning" : "snapshots.takeOff")}</p>
      <label className="snap-field">
        <span>{t("snapshots.name")}</span>
        <input type="text" value={name} autoFocus onChange={(e) => setName(e.target.value)} />
      </label>
      {taken && <p className="field-error">{t("snapshots.nameTaken")}</p>}
      <label className="snap-field">
        <span>{t("snapshots.description")}</span>
        <textarea rows={4} value={description} onChange={(e) => setDescription(e.target.value)} />
      </label>
    </Dialog>
  );
}
