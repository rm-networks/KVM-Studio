import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import "./AboutDialog.css";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  version: string | undefined;
}

export function AboutDialog({ open, onOpenChange, version }: Props) {
  const { t } = useTranslation();
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog about">
          <div className="dialog-titlebar">
            <Dialog.Title className="dialog-title">{t("about.title")}</Dialog.Title>
            <Dialog.Close className="dialog-x" aria-label={t("about.close")}>
              <X size={14} />
            </Dialog.Close>
          </div>
          <div className="dialog-body">
            <p className="about-name">KVM Studio</p>
            {version && <p className="about-version">{t("about.version", { version })}</p>}
            <Dialog.Description>{t("about.description")}</Dialog.Description>
            <p>{t("about.license")}</p>
            <p className="about-notice">{t("about.notice")}</p>
          </div>
          <div className="dialog-buttons">
            <Dialog.Close className="button">{t("about.close")}</Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
