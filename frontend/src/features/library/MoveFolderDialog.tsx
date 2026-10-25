import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError, type FolderMovePlan } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { ErrorMessage } from "../../components/ErrorMessage";
import { useNotifier } from "../../components/notifier";
import "../vm/DeleteDialog.css";

interface Props {
  path: string;
  parent: string;
  before: string | null;
  onClose: () => void;
}

/** Moving a folder moves the files of its VMs: the list is shown before. */
export function MoveFolderDialog({ path, parent, before, onClose }: Props) {
  const { t } = useTranslation();
  const { notifyError } = useNotifier();
  const [plan, setPlan] = useState<FolderMovePlan | null>(null);
  const [planError, setPlanError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .folderMovePlan(path, parent)
      .then((p) => !cancelled && setPlan(p))
      .catch((err: unknown) => {
        if (!cancelled) {
          setPlanError(err instanceof ApiError ? err : new ApiError(0, "http.error", String(err)));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [path, parent]);

  const ready = plan !== null && plan.running.length === 0 && plan.blockers.length === 0;
  const target = parent || t("library.myComputer");

  const confirm = () => {
    setBusy(true);
    api
      .moveFolder(path, parent, before)
      .then(onClose)
      .catch((err: unknown) => {
        setBusy(false);
        notifyError(t("library.moveFolderFailed", { folder: path }), err);
      });
  };

  return (
    <Dialog
      open
      width={560}
      onOpenChange={(open) => !open && onClose()}
      title={t("library.moveFolderTitle")}
      buttons={
        <>
          <button
            type="button"
            className="button button-primary"
            disabled={!ready || busy}
            onClick={confirm}
          >
            {t("library.moveFolderConfirm")}
          </button>
          <button type="button" className="button" onClick={onClose} autoFocus>
            {t("common.cancel")}
          </button>
        </>
      }
    >
      <p>{t("library.moveFolderIntro", { folder: path, target })}</p>
      {planError && <ErrorMessage error={planError} />}
      {!plan && !planError && <p className="delete-muted">{t("library.loading")}</p>}
      {plan && plan.running.length > 0 && (
        <p className="field-error">
          {t("library.powerOffFirst", { names: plan.running.join(", ") })}
        </p>
      )}
      {plan && plan.blockers.length > 0 && (
        <p className="field-error">
          {t("library.moveFolderLinked", { files: plan.blockers.join(", ") })}
        </p>
      )}
      {plan && (
        <>
          <h3 className="delete-heading">{t("library.vmsMoved", { count: plan.vms.length })}</h3>
          {plan.vms.length > 0 ? (
            <ul className="delete-files">
              {plan.vms.map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ul>
          ) : (
            <p className="delete-muted">{t("library.noVmInFolder")}</p>
          )}
          <p className="delete-muted">{t("library.moveFolderWhere", { target: plan.target })}</p>
        </>
      )}
    </Dialog>
  );
}
