import * as RadixDialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import "./Dialog.css";
import { focusFirstField } from "./focus";
import { useDragMove } from "./useDragMove";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
  /** Right of the footer: OK, Cancel, Apply. */
  buttons: ReactNode;
  /** Left of the footer, for actions that do not close the dialog. */
  extraButtons?: ReactNode;
  width?: number;
}

export function Dialog({
  open,
  onOpenChange,
  title,
  children,
  buttons,
  extraButtons,
  width = 440,
}: Props) {
  const { t } = useTranslation();
  const drag = useDragMove(open);
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="dialog-overlay" />
        <RadixDialog.Content
          className="dialog"
          style={{ ...drag.style, width: `min(${width}px, calc(100vw - 32px))` }}
          aria-describedby={undefined}
          onOpenAutoFocus={(e) =>
            focusFirstField(e, ".dialog-body", ".dialog-buttons .button-primary")
          }
        >
          <div className="dialog-titlebar" onPointerDown={drag.onPointerDown}>
            <RadixDialog.Title className="dialog-title">{title}</RadixDialog.Title>
            <RadixDialog.Close className="icon-button" aria-label={t("about.close")}>
              <X />
            </RadixDialog.Close>
          </div>
          <div className="dialog-body">{children}</div>
          <div className="dialog-buttons">
            {extraButtons && <div className="dialog-buttons-start">{extraButtons}</div>}
            {buttons}
          </div>
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
