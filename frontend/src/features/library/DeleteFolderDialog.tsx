import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, type FolderDeletionPlan } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { ErrorMessage } from "../../components/ErrorMessage";
import { useNotifier } from "../../components/notifier";
import "../vm/DeleteDialog.css";

export function DeleteFolderDialog({ path, onClose }: { path: string; onClose: () => void }) {
  const { t } = useTranslation();
  const { notify, notifyError } = useNotifier();
  const [plan, setPlan] = useState<FolderDeletionPlan | null>(null);
  const [planError, setPlanError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .folderDeletionPlan(path)
      .then((p) => !cancelled && setPlan(p))
      .catch((err: unknown) => {
        if (!cancelled) {
          setPlanError(err instanceof ApiError ? err : new ApiError(0, "http.error", String(err)));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  const files = plan ? [...plan.vms.flatMap((v) => v.delete), ...plan.extra_files] : [];
  const keep = plan ? [...plan.vms.flatMap((v) => v.keep), ...plan.keep] : [];
  const ready = plan !== null && plan.running.length === 0;

  const confirm = () => {
    setBusy(true);
    api
      .deleteFolder(path)
      .then((result) => {
        onClose();
        if (result.failed.length > 0) {
          notify(t("library.deletePartial", { folder: path }), result.failed.join("\n"));
        }
      })
      .catch((err: unknown) => {
        setBusy(false);
        notifyError(t("library.deleteFolderTitle"), err);
      });
  };

  return (
    <Dialog
      open
      width={580}
      onOpenChange={(open) => !open && onClose()}
      title={t("library.deleteFolderTitle")}
      buttons={
        <>
          <button
            type="button"
            className="button button-danger"
            disabled={!ready || busy}
            onClick={confirm}
          >
            {t("delete.confirmFiles")}
          </button>
          <button type="button" className="button" onClick={onClose} autoFocus>
            {t("common.cancel")}
          </button>
        </>
      }
    >
      <p>{t("library.deleteFolderIntro", { folder: path })}</p>
      {planError && <ErrorMessage error={planError} />}
      {!plan && !planError && <p className="delete-muted">{t("library.loading")}</p>}
      {plan && plan.running.length > 0 && (
        <p className="field-error">
          {t("library.powerOffFirst", { names: plan.running.join(", ") })}
        </p>
      )}
      {plan && (
        <>
          <h3 className="delete-heading">{t("library.vmsRemoved", { count: plan.vms.length })}</h3>
          {plan.vms.length > 0 ? (
            <ul className="delete-files">
              {plan.vms.map((v) => (
                <li key={v.uuid}>{v.name}</li>
              ))}
            </ul>
          ) : (
            <p className="delete-muted">{t("library.noVmInFolder")}</p>
          )}
          <h3 className="delete-heading">{t("delete.willDelete", { count: files.length })}</h3>
          {files.length > 0 ? (
            <ul className="delete-files delete-files-danger">
              {files.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          ) : (
            <p className="delete-muted">{t("delete.nothingToDelete")}</p>
          )}
          {keep.length > 0 && (
            <>
              <h3 className="delete-heading">{t("delete.willKeep")}</h3>
              <ul className="delete-files">
                {keep.map((k) => (
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
