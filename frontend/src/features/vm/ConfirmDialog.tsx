import { useTranslation } from "react-i18next";

import { Dialog } from "../../components/Dialog";

interface Props {
  title: string;
  message: string;
  confirmLabel: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  danger,
  onConfirm,
  onCancel,
}: Props) {
  const { t } = useTranslation();
  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onCancel()}
      title={title}
      buttons={
        <>
          <button
            type="button"
            className={danger ? "button button-danger" : "button button-primary"}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
          <button type="button" className="button" onClick={onCancel} autoFocus>
            {t("common.cancel")}
          </button>
        </>
      }
    >
      <p>{message}</p>
    </Dialog>
  );
}
