import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, type DeletionPlan, type VmSummary } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { ErrorMessage } from "../../components/ErrorMessage";
import { useNotifier } from "../../components/notifier";
import "./DeleteDialog.css";

interface Props {
  vm: VmSummary;
  /** true: "Delete from disk"; false: only remove it from the library. */
  deleteFiles: boolean;
  onClose: () => void;
}

export function DeleteDialog({ vm, deleteFiles, onClose }: Props) {
  const { t } = useTranslation();
  const { notify, notifyError } = useNotifier();
  const [plan, setPlan] = useState<DeletionPlan | null>(null);
  const [planError, setPlanError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const running = vm.state !== "shutoff";

  useEffect(() => {
    if (!deleteFiles) return;
    let cancelled = false;
    api
      .deletionPlan(vm.uuid)
      .then((p) => !cancelled && setPlan(p))
      .catch((err: unknown) => {
        if (!cancelled)
          setPlanError(err instanceof ApiError ? err : new ApiError(0, "http.error", String(err)));
      });
    return () => {
      cancelled = true;
    };
  }, [vm.uuid, deleteFiles]);

  const ready = !running && (!deleteFiles || plan !== null);

  const confirm = () => {
    setBusy(true);
    api
      .deleteVm(vm.uuid, deleteFiles)
      .then((result) => {
        onClose();
        if (result.failed.length > 0) {
          notify(t("delete.partial", { name: vm.name }), result.failed.join("\n"));
        }
      })
      .catch((err: unknown) => {
        setBusy(false);
        notifyError(t("delete.failed", { name: vm.name }), err);
      });
  };

  return (
    <Dialog
      open
      width={560}
      onOpenChange={(open) => !open && onClose()}
      title={deleteFiles ? t("delete.titleFiles") : t("delete.titleRemove")}
      buttons={
        <>
          <button
            type="button"
            className="button button-danger"
            disabled={!ready || busy}
            onClick={confirm}
          >
            {deleteFiles ? t("delete.confirmFiles") : t("delete.confirmRemove")}
          </button>
          <button type="button" className="button" onClick={onClose} autoFocus>
            {t("common.cancel")}
          </button>
        </>
      }
    >
      <p>
        {deleteFiles
          ? t("delete.introFiles", { name: vm.name })
          : t("delete.introRemove", { name: vm.name })}
      </p>
      {running && <p className="field-error">{t("delete.mustBeOff")}</p>}
      {deleteFiles && planError && <ErrorMessage error={planError} />}
      {deleteFiles && !plan && !planError && <p className="delete-muted">{t("library.loading")}</p>}
      {deleteFiles && plan && (
        <>
          <h3 className="delete-heading">
            {t("delete.willDelete", { count: plan.delete.length })}
          </h3>
          {plan.delete.length > 0 ? (
            <ul className="delete-files delete-files-danger">
              {plan.delete.map((path) => (
                <li key={path}>{path}</li>
              ))}
            </ul>
          ) : (
            <p className="delete-muted">{t("delete.nothingToDelete")}</p>
          )}
          {plan.keep.length > 0 && (
            <>
              <h3 className="delete-heading">{t("delete.willKeep")}</h3>
              <ul className="delete-files">
                {plan.keep.map((k) => (
                  <li key={k.path}>
                    {k.path}
                    <span className="delete-reason">{t(`delete.reason.${k.reason}`)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </Dialog>
  );
}
