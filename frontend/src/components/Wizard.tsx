import * as RadixDialog from "@radix-ui/react-dialog";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import "./Wizard.css";
import { focusFirstField } from "./focus";

interface Props {
  /** Name of the assistant, for assistive technologies and the window title. */
  name: string;
  /** Title of the current page; never numbered. */
  title: string;
  /** Position among the pages the user goes through, from 0. */
  step: number;
  steps: number;
  children: ReactNode;
  /** Footer buttons, right-aligned: Cancel, Back, Next. */
  buttons: ReactNode;
  /** In the main window, or alone in its own window (uninstall). */
  mode?: "dialog" | "window";
  width?: number;
  onCancel?: () => void;
}

function Frame({ title, step, steps, children, buttons }: Omit<Props, "name">) {
  const { t } = useTranslation();
  const progress = steps > 1 ? (step / (steps - 1)) * 100 : 100;
  return (
    <>
      <header className="wizard-header">
        <img className="wizard-logo" src="/logo.png" alt="" width={32} height={32} />
        <div className="wizard-heading">
          <h2 className="wizard-title">{title}</h2>
          <span className="wizard-count">
            {t("wizard.stepOf", { step: step + 1, count: steps })}
          </span>
        </div>
        <div
          className="wizard-progress"
          role="progressbar"
          aria-valuemin={1}
          aria-valuemax={steps}
          aria-valuenow={step + 1}
        >
          <span style={{ width: `${progress}%` }} />
        </div>
      </header>
      <div className="wizard-content">{children}</div>
      <footer className="wizard-footer">{buttons}</footer>
    </>
  );
}

export function Wizard({ name, mode = "dialog", width = 680, onCancel, ...frame }: Props) {
  if (mode === "window") {
    return (
      <main className="wizard wizard-window" aria-label={name}>
        <Frame {...frame} />
      </main>
    );
  }
  return (
    <RadixDialog.Root open onOpenChange={(open) => !open && onCancel?.()}>
      <RadixDialog.Portal>
        <RadixDialog.Overlay className="dialog-overlay" />
        <RadixDialog.Content
          className="wizard wizard-dialog"
          style={{ width: `min(${width}px, calc(100vw - 32px))` }}
          aria-describedby={undefined}
          aria-label={name}
          onOpenAutoFocus={(e) =>
            focusFirstField(e, ".wizard-content", ".wizard-footer .button-primary")
          }
        >
          <RadixDialog.Title className="visually-hidden">{name}</RadixDialog.Title>
          <Frame {...frame} />
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  );
}
