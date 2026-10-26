import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type SnapshotLimits, type VmSummary } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import "./SnapshotManager.css";
import { SNAPSHOT_NAME_MAX, snapshotNameProblem } from "./snapshotName";

interface Props {
  vm: VmSummary;
  existing: string[];
  onTake: (name: string, description: string, memory: boolean) => void;
  onClose: () => void;
}

/** Name, description and memory of a new snapshot, with what libvirt cannot do. */
export function TakeSnapshotDialog({ vm, existing, onTake, onClose }: Props) {
  const { t } = useTranslation();
  let n = existing.length + 1;
  while (existing.includes(t("snapshots.defaultName", { n }))) n += 1;
  const [name, setName] = useState(t("snapshots.defaultName", { n }));
  const [description, setDescription] = useState("");
  const [limits, setLimits] = useState<SnapshotLimits | null>(null);
  const [memory, setMemory] = useState(true);
  const taken = existing.includes(name);
  const problem = snapshotNameProblem(name);
  const running = limits?.running ?? (vm.state === "running" || vm.state === "paused");

  useEffect(() => {
    let cancelled = false;
    api
      .snapshotLimits(vm.uuid)
      .then((found) => !cancelled && setLimits(found))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [vm.uuid]);

  const raw = limits !== null && (limits.raw_disks.length > 0 || limits.raw_nvram);
  const blocked = raw || (running && !memory);

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
            disabled={problem !== null || taken || blocked}
            onClick={() => {
              onTake(name, description, running && memory);
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
        <input
          type="text"
          value={name}
          maxLength={SNAPSHOT_NAME_MAX + 1}
          autoFocus
          aria-invalid={problem !== null && problem.kind !== "empty"}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      {problem?.kind === "char" && (
        <p className="field-error">
          {t(problem.char === " " ? "snapshots.nameSpace" : "snapshots.nameChar", {
            char: problem.char,
          })}{" "}
          {t("snapshots.nameAllowed")}
        </p>
      )}
      {problem?.kind === "dot" && <p className="field-error">{t("snapshots.nameDot")}</p>}
      {problem?.kind === "long" && (
        <p className="field-error">{t("snapshots.nameLong", { max: SNAPSHOT_NAME_MAX })}</p>
      )}
      {taken && <p className="field-error">{t("snapshots.nameTaken")}</p>}
      <label className="snap-field">
        <span>{t("snapshots.description")}</span>
        <textarea rows={4} value={description} onChange={(e) => setDescription(e.target.value)} />
      </label>
      <label className="check" title={t("snapshots.memoryHint")}>
        <input
          type="checkbox"
          checked={running && memory}
          disabled={!running}
          onChange={(e) => setMemory(e.target.checked)}
        />
        {t("snapshots.memory")}
      </label>
      {running && !memory && <p className="field-error">{t("snapshots.memoryRequired")}</p>}
      {limits?.raw_disks.length ? (
        <p className="field-error">
          {t("snapshots.rawDisks", { disks: limits.raw_disks.join(", ") })}
        </p>
      ) : null}
      {limits?.raw_nvram && <p className="field-error">{t("snapshots.rawNvram")}</p>}
      {limits?.tpm && !running && <p className="check-hint">{t("snapshots.tpmOff")}</p>}
    </Dialog>
  );
}
