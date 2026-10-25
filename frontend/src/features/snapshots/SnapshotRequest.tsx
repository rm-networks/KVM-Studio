import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type VmSummary } from "../../api/client";
import { useNotifier } from "../../components/notifier";
import { useTasks } from "../../components/taskTracker";
import { ConfirmDialog } from "../vm/ConfirmDialog";
import { SnapshotManager } from "./SnapshotManager";
import { TakeSnapshotDialog } from "./TakeSnapshotDialog";

export type SnapshotKind = "take" | "revert" | "manager";

/** Toolbar and VM menu: take a snapshot, go back to the current one, or open the manager. */
export function SnapshotRequest({
  vm,
  kind,
  onClose,
}: {
  vm: VmSummary;
  kind: SnapshotKind;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const { notify, notifyError } = useNotifier();
  const { track } = useTasks();
  const [names, setNames] = useState<string[] | null>(null);
  const [current, setCurrent] = useState<string | null>(null);

  useEffect(() => {
    if (kind === "manager") return;
    let cancelled = false;
    api
      .snapshots(vm.uuid)
      .then((snaps) => {
        if (cancelled) return;
        const here = snaps.find((s) => s.current)?.name ?? null;
        if (kind === "revert" && here === null) {
          notify(t("snapshots.revert"), t("snapshots.noCurrent", { name: vm.name }));
          onClose();
          return;
        }
        setNames(snaps.map((s) => s.name));
        setCurrent(here);
      })
      .catch((err: unknown) => {
        notifyError(t("snapshots.title", { name: vm.name }), err);
        onClose();
      });
    return () => {
      cancelled = true;
    };
  }, [vm, kind, notify, notifyError, onClose, t]);

  if (kind === "manager") return <SnapshotManager vm={vm} onClose={onClose} />;
  if (names === null) return null;
  if (kind === "take") {
    return (
      <TakeSnapshotDialog
        vm={vm}
        existing={names}
        onClose={onClose}
        onTake={(name, description, memory) =>
          void api
            .takeSnapshot(vm.uuid, name, description, memory)
            .then((info) =>
              track(
                info,
                t("snapshots.started", { name: vm.name }),
                t("snapshots.taken", { name }),
              ),
            )
            .catch((err: unknown) => notifyError(t("snapshots.take"), err))
        }
      />
    );
  }
  return (
    <ConfirmDialog
      title={t("snapshots.revert")}
      message={t("snapshots.confirmRevert", { name: vm.name, snapshot: current ?? "" })}
      confirmLabel={t("snapshots.revert")}
      danger
      onCancel={onClose}
      onConfirm={() => {
        onClose();
        api
          .revertSnapshot(vm.uuid, current ?? "")
          .catch((err: unknown) => notifyError(t("snapshots.revert"), err));
      }}
    />
  );
}
