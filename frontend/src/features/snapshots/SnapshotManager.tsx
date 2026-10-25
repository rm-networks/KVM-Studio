import { Camera, MapPin } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type Snapshot, type VmSummary } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { useNotifier } from "../../components/notifier";
import { ConfirmDialog } from "../vm/ConfirmDialog";
import { treeRows } from "./snapshotTree";
import { TakeSnapshotDialog } from "./TakeSnapshotDialog";
import "./SnapshotManager.css";

type Pending = { kind: "take" } | { kind: "revert" | "delete"; name: string } | null;

export function SnapshotManager({ vm, onClose }: { vm: VmSummary; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const { notifyError } = useNotifier();
  const [snaps, setSnaps] = useState<Snapshot[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [pending, setPending] = useState<Pending>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    () =>
      api
        .snapshots(vm.uuid)
        .then(setSnaps)
        .catch((err: unknown) => {
          setSnaps([]);
          notifyError(t("snapshots.title", { name: vm.name }), err);
        }),
    [vm.uuid, vm.name, notifyError, t],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const run = (title: string, action: () => Promise<unknown>) => {
    setBusy(true);
    action()
      .catch((err: unknown) => notifyError(title, err))
      .finally(() => {
        setBusy(false);
        void load();
      });
  };

  const rows = treeRows(snaps ?? []);
  const current = snaps?.find((s) => s.current)?.name ?? null;
  const snap = snaps?.find((s) => s.name === selected) ?? null;
  const date = (seconds: number) =>
    new Date(seconds * 1000).toLocaleString(i18n.language, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  // "You are here" sits under the current snapshot, or at the top without one.
  const hereDepth = current ? (rows.find((r) => r.snap.name === current)?.depth ?? -1) + 1 : 0;
  const here = (
    <li key="here" className="snap-row snap-here" style={{ paddingLeft: 8 + hereDepth * 18 }}>
      <MapPin aria-hidden />
      {t("snapshots.youAreHere")}
    </li>
  );

  return (
    <>
      <Dialog
        open
        width={720}
        onOpenChange={(open) => !open && onClose()}
        title={t("snapshots.title", { name: vm.name })}
        buttons={
          <button type="button" className="button" onClick={onClose}>
            {t("common.close")}
          </button>
        }
      >
        <div className="snap-manager">
          <ul className="list snap-tree" role="listbox" aria-label={t("snapshots.list")}>
            {current === null && here}
            {rows.map(({ snap: s, depth }) => [
              <li
                key={s.name}
                role="option"
                aria-selected={s.name === selected}
                className="list-row snap-row"
                style={{ paddingLeft: 8 + depth * 18 }}
                onClick={() => setSelected(s.name)}
              >
                <Camera aria-hidden />
                {s.name}
              </li>,
              s.name === current ? here : null,
            ])}
            {snaps !== null && snaps.length === 0 && (
              <li className="list-empty">{t("snapshots.none")}</li>
            )}
          </ul>
          <div className="snap-side">
            {snap ? (
              <>
                <h3 className="snap-name">{snap.name}</h3>
                <p className="muted">
                  {date(snap.created)} ·{" "}
                  {t(snap.state === "shutoff" ? "snapshots.takenOff" : "snapshots.takenOn")}
                </p>
                <p className="snap-description">
                  {snap.description || (
                    <span className="muted">{t("snapshots.noDescription")}</span>
                  )}
                </p>
              </>
            ) : (
              <p className="muted">{t("snapshots.pick")}</p>
            )}
            <div className="snap-buttons">
              <button
                type="button"
                className="button"
                disabled={busy}
                onClick={() => setPending({ kind: "take" })}
              >
                {t("snapshots.take")}
              </button>
              <button
                type="button"
                className="button"
                disabled={busy || !snap}
                onClick={() => snap && setPending({ kind: "revert", name: snap.name })}
              >
                {t("snapshots.revert")}
              </button>
              <button
                type="button"
                className="button"
                disabled={busy || !snap}
                onClick={() => snap && setPending({ kind: "delete", name: snap.name })}
              >
                {t("snapshots.delete")}
              </button>
            </div>
            {busy && <p className="muted">{t("snapshots.working")}</p>}
          </div>
        </div>
        <p className="check-hint">{t("snapshots.hint")}</p>
      </Dialog>
      {pending?.kind === "take" && (
        <TakeSnapshotDialog
          vm={vm}
          existing={(snaps ?? []).map((s) => s.name)}
          onTake={(name, description) =>
            run(t("snapshots.take"), () => api.takeSnapshot(vm.uuid, name, description))
          }
          onClose={() => setPending(null)}
        />
      )}
      {pending && pending.kind !== "take" && (
        <ConfirmDialog
          title={pending.kind === "revert" ? t("snapshots.revert") : t("snapshots.delete")}
          message={
            pending.kind === "revert"
              ? t("snapshots.confirmRevert", { name: vm.name, snapshot: pending.name })
              : t("snapshots.confirmDelete", { snapshot: pending.name })
          }
          confirmLabel={pending.kind === "revert" ? t("snapshots.revert") : t("snapshots.delete")}
          danger
          onCancel={() => setPending(null)}
          onConfirm={() => {
            const { kind, name } = pending;
            setPending(null);
            run(kind === "revert" ? t("snapshots.revert") : t("snapshots.delete"), () =>
              kind === "revert"
                ? api.revertSnapshot(vm.uuid, name)
                : api.deleteSnapshot(vm.uuid, name),
            );
          }}
        />
      )}
    </>
  );
}
