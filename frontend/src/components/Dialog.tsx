import * as RadixDialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import "./Dialog.css";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
  buttons: ReactNode;
  width?: number;
}

export function Dialog({ open, onOpenChange, title, children, buttons, width = 440 }: Props) {
  const { t } = useTranslation();
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="dialog-overlay" />
        <RadixDialog.Content className="dialog" style={{ width }} aria-describedby={undefined}>
          <div className="dialog-titlebar">
            <RadixDialog.Title className="dialog-title">{title}</RadixDialog.Title>
            <RadixDialog.Close className="dialog-x" aria-label={t("about.close")}>
              <X size={14} />
            </RadixDialog.Close>
          </div>
          <div className="dialog-body">{children}</div>
          <div className="dialog-buttons">{buttons}</div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
