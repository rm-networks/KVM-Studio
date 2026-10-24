import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { Dialog } from "./Dialog";
import { useNotifier } from "./notifier";

interface Props {
  title: string;
  label: string;
  initial: string;
  confirmLabel: string;
  /** Returns an error message, or null when the value is acceptable. */
  validate: (value: string) => string | null;
  onSubmit: (value: string) => Promise<unknown>;
  onClose: () => void;
}

export function PromptDialog({
  title,
  label,
  initial,
  confirmLabel,
  validate,
  onSubmit,
  onClose,
}: Props) {
  const { t } = useTranslation();
  const { notifyError } = useNotifier();
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  const problem = value === initial ? null : validate(value);
  const ready = value !== initial && problem === null && !busy;

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (!ready) return;
    setBusy(true);
    onSubmit(value).catch((err: unknown) => {
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
            disabled={!ready}
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
        <label className="field">
          <span>{label}</span>
          <input type="text" value={value} autoFocus onChange={(e) => setValue(e.target.value)} />
        </label>
        {problem && <p className="field-error">{problem}</p>}
      </form>
    </Dialog>
  );
}
