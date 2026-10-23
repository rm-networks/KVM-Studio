import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { Dialog } from "../../components/Dialog";
import { useNotifier } from "../../components/notifier";
import { isValidName } from "./names";

interface Props {
  title: string;
  parent: string;
  initial: string;
  confirmLabel: string;
  onSubmit: (name: string) => Promise<unknown>;
  onClose: () => void;
}

export function FolderNameDialog({
  title,
  parent,
  initial,
  confirmLabel,
  onSubmit,
  onClose,
}: Props) {
  const { t } = useTranslation();
  const { notifyError } = useNotifier();
  const [name, setName] = useState(initial);
  const [busy, setBusy] = useState(false);
  const valid = isValidName(name) && name !== initial;

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (!valid || busy) return;
    setBusy(true);
    onSubmit(name).catch((err: unknown) => {
      setBusy(false);
      notifyError(title, err);
    });
  };

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={title}
      buttons={
        <>
          <button
            type="button"
            className="button button-primary"
            disabled={!valid || busy}
            onClick={() => submit()}
          >
            {confirmLabel}
          </button>
          <button type="button" className="button" onClick={onClose}>
            {t("common.cancel")}
          </button>
        </>
      }
    >
      <form onSubmit={submit}>
        <p className="dialog-muted">
          {t("library.inFolder", { folder: parent || t("library.myComputer") })}
        </p>
        <label className="field">
          <span>{t("library.folderName")}</span>
          <input
            type="text"
            value={name}
            maxLength={64}
            autoFocus
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        {name !== "" && !isValidName(name) && <p className="field-error">{t("rename.invalid")}</p>}
      </form>
    </Dialog>
  );
}
