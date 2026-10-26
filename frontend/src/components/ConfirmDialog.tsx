import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import "./ConfirmDialog.css";
import { Dialog } from "./Dialog";
import { useNotifier } from "./notifier";

interface Props {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  /** Busy label while onConfirm runs. */
  busyLabel?: string;
  onConfirm: () => Promise<unknown>;
  onClose: () => void;
}

/** Asks before an action that changes files; the action runs from here. */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  busyLabel,
  onConfirm,
  onClose,
}: Props) {
  const { t } = useTranslation();
  const { notifyError } = useNotifier();
  const [busy, setBusy] = useState(false);
  return (
    <Dialog
      open
      width={560}
      onOpenChange={(o) => !o && !busy && onClose()}
      title={title}
      buttons={
        <>
          <button
            type="button"
            className="button button-primary"
            disabled={busy}
            onClick={() => {
              setBusy(true);
              onConfirm().then(onClose, (err: unknown) => {
                setBusy(false);
                notifyError(title, err);
              });
            }}
          >
            {busy && busyLabel ? busyLabel : confirmLabel}
          </button>
          <button type="button" className="button" disabled={busy} onClick={onClose}>
            {t("common.cancel")}
          </button>
        </>
      }
    >
      {children}
    </Dialog>
  );
}
