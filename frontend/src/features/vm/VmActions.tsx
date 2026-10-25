import { type ReactNode, useCallback, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, type PowerAction, type VmSummary } from "../../api/client";
import { useNotifier } from "../../components/notifier";
import { CloneWizard } from "../clone/CloneWizard";
import { cancelStart, noteStart } from "../console/bootSplash";
import { ConfirmDialog } from "./ConfirmDialog";
import { DeleteDialog } from "./DeleteDialog";
import { RenameDialog } from "./RenameDialog";
import { type VmActions, VmActionsContext } from "./vmActionsContext";

// Actions that can lose unsaved work in the guest ask first (rule 11).
const NEEDS_CONFIRMATION: ReadonlySet<PowerAction> = new Set(["poweroff", "reset"]);

type Pending =
  | { kind: "confirm"; vm: VmSummary; action: PowerAction }
  | { kind: "rename"; vm: VmSummary }
  | { kind: "delete"; vm: VmSummary; deleteFiles: boolean }
  | { kind: "clone"; vm: VmSummary }
  // Starting a VM whose disks are the base of linked clones.
  | { kind: "linked"; vm: VmSummary; clones: string }
  | null;

export function VmActionsProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const { notifyError } = useNotifier();
  const [pending, setPending] = useState<Pending>(null);

  const runPower = useCallback(
    (vm: VmSummary, action: PowerAction, force = false) => {
      if (action === "start") noteStart(vm.uuid);
      api.power(vm.uuid, action, force).catch((err: unknown) => {
        if (action === "start") cancelStart(vm.uuid);
        if (err instanceof ApiError && err.code === "vm.has_linked_clones") {
          const clones = err.detail.slice(err.detail.indexOf(":") + 1).trim();
          setPending({ kind: "linked", vm, clones });
          return;
        }
        notifyError(t("actions.failed", { action: t(`power.${action}`), name: vm.name }), err);
      });
    },
    [notifyError, t],
  );

  const actions = useMemo<VmActions>(
    () => ({
      power: (vm, action) => {
        if (NEEDS_CONFIRMATION.has(action)) setPending({ kind: "confirm", vm, action });
        else runPower(vm, action);
      },
      rename: (vm) => setPending({ kind: "rename", vm }),
      remove: (vm, deleteFiles) => setPending({ kind: "delete", vm, deleteFiles }),
      clone: (vm) => setPending({ kind: "clone", vm }),
    }),
    [runPower],
  );

  const close = () => setPending(null);

  return (
    <VmActionsContext.Provider value={actions}>
      {children}
      {pending?.kind === "confirm" && (
        <ConfirmDialog
          title={t(`power.${pending.action}`)}
          message={t(`power.confirm.${pending.action}`, { name: pending.vm.name })}
          confirmLabel={t(`power.${pending.action}`)}
          danger
          onConfirm={() => {
            runPower(pending.vm, pending.action);
            close();
          }}
          onCancel={close}
        />
      )}
      {pending?.kind === "linked" && (
        <ConfirmDialog
          title={t("clone.startSourceTitle")}
          message={t("clone.startSource", { name: pending.vm.name, clones: pending.clones })}
          confirmLabel={t("clone.startAnyway")}
          danger
          onConfirm={() => {
            runPower(pending.vm, "start", true);
            close();
          }}
          onCancel={close}
        />
      )}
      {pending?.kind === "clone" && <CloneWizard source={pending.vm} onClose={close} />}
      {pending?.kind === "rename" && <RenameDialog vm={pending.vm} onClose={close} />}
      {pending?.kind === "delete" && (
        <DeleteDialog vm={pending.vm} deleteFiles={pending.deleteFiles} onClose={close} />
      )}
    </VmActionsContext.Provider>
  );
}
