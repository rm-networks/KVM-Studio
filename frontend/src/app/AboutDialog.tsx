import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { APP_NAME } from "../brand";
import "../components/Dialog.css";
import { focusFirstField } from "../components/focus";
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
        <Dialog.Content
          className="dialog"
          style={{ width: "min(460px, calc(100vw - 32px))" }}
          onOpenAutoFocus={(e) => focusFirstField(e, ".dialog-body", ".dialog-buttons .button")}
        >
          <div className="dialog-titlebar">
            <Dialog.Title className="dialog-title">{t("about.title")}</Dialog.Title>
            <Dialog.Close className="icon-button" aria-label={t("about.close")}>
              <X />
            </Dialog.Close>
          </div>
          <div className="dialog-body">
            <div className="about-head">
              <img src="/logo.png" alt="" width={56} height={56} />
              <div>
                <p className="about-name">{APP_NAME}</p>
                {version && <p className="about-version">{t("about.version", { version })}</p>}
              </div>
            </div>
            <Dialog.Description>{t("about.description")}</Dialog.Description>
            <p>{t("about.license")}</p>
            <p className="about-notice">{t("about.notice")}</p>
          </div>
          <div className="dialog-buttons">
            <Dialog.Close className="button button-primary">{t("about.close")}</Dialog.Close>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
