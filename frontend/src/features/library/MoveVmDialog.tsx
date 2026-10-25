import { Folder, MonitorSmartphone } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { VmSummary } from "../../api/client";
import { Dialog } from "../../components/Dialog";
import { useNotifier } from "../../components/notifier";
import "./MoveVmDialog.css";

interface Props {
  vm: VmSummary;
  folders: string[];
  /** Copy an outside VM's disks into the library instead of a plain move. */
  importFiles: boolean;
  onSubmit: (folder: string) => Promise<unknown>;
  onClose: () => void;
}

export function MoveVmDialog({ vm, folders, importFiles, onSubmit, onClose }: Props) {
  const { t } = useTranslation();
  const { notifyError } = useNotifier();
  const [target, setTarget] = useState(vm.folder);
  const [busy, setBusy] = useState(false);
  const running = vm.state !== "shutoff";
  const blocked = (importFiles || vm.managed) && running;
  const unchanged = !importFiles && target === vm.folder;
  const title = importFiles ? t("library.importTitle") : t("library.moveTitle");

  const submit = () => {
    setBusy(true);
    onSubmit(target).catch((err: unknown) => {
      setBusy(false);
      notifyError(title, err);
    });
  };

  const choices = ["", ...folders];

  return (
    <Dialog
      open
      width={480}
      onOpenChange={(open) => !open && onClose()}
      title={title}
      buttons={
        <>
          <button
            type="button"
            className="button button-primary"
            disabled={blocked || unchanged || busy}
            onClick={submit}
          >
            {busy && importFiles ? t("library.copying") : t("library.move")}
          </button>
          <button type="button" className="button" onClick={onClose} disabled={busy}>
            {t("common.cancel")}
          </button>
        </>
      }
    >
      <p>
        {importFiles
          ? t("library.importIntro", { name: vm.name })
          : vm.managed
            ? t("library.moveIntroFiles", { name: vm.name })
            : t("library.moveIntroVirtual", { name: vm.name })}
      </p>
      {blocked && <p className="field-error">{t("delete.mustBeOff")}</p>}
      <ul className="list folder-choices" role="listbox" aria-label={t("library.destination")}>
        {choices.map((path) => {
          const depth = path ? path.split("/").length : 0;
          return (
            <li
              key={path}
              role="option"
              aria-selected={target === path}
              className={target === path ? "selected" : undefined}
              style={{ paddingLeft: 6 + depth * 16 }}
              onClick={() => setTarget(path)}
            >
              {path ? <Folder aria-hidden /> : <MonitorSmartphone aria-hidden />}
              {path ? path.slice(path.lastIndexOf("/") + 1) : t("library.myComputer")}
            </li>
          );
        })}
      </ul>
    </Dialog>
  );
}
