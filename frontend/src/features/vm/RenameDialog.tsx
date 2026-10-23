import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, type VmSummary } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { useNotifier } from "../../components/notifier";

// Same rule as the backend: names become folder names.
// eslint-disable-next-line no-control-regex -- control characters are what we reject
const NAME_RE = /^(?![.\s])[^/\\\u0000-\u001f\u007f]{1,64}(?<!\s)$/;

export function RenameDialog({ vm, onClose }: { vm: VmSummary; onClose: () => void }) {
  const { t } = useTranslation();
  const { notifyError } = useNotifier();
  const [name, setName] = useState(vm.name);
  const [busy, setBusy] = useState(false);
  const valid = NAME_RE.test(name);
  const running = vm.state !== "shutoff";

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (!valid || running || name === vm.name) return;
    setBusy(true);
    api
      .rename(vm.uuid, name)
      .then(onClose)
      .catch((err: unknown) => {
        setBusy(false);
        notifyError(t("rename.failed", { name: vm.name }), err);
      });
  };

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title={t("rename.title")}
      buttons={
        <>
          <button
            type="button"
            className="button button-primary"
            disabled={!valid || running || busy || name === vm.name}
            onClick={() => submit()}
          >
            {t("rename.confirm")}
          </button>
          <button type="button" className="button" onClick={onClose}>
            {t("common.cancel")}
          </button>
        </>
      }
    >
      <form onSubmit={submit}>
        <label className="field">
          <span>{t("rename.label")}</span>
          <input
            type="text"
            value={name}
            maxLength={64}
            autoFocus
            disabled={running}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        {running && <p className="field-error">{t("rename.mustBeOff")}</p>}
        {!running && !valid && <p className="field-error">{t("rename.invalid")}</p>}
      </form>
    </Dialog>
  );
}
