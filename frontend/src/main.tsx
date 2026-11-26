// Shared styles first: the screens' own sheets come after them.
import "./styles/tokens.css";
import "./styles/controls.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { captureToken } from "./api/token";
import { Gate } from "./app/Gate";
import { NotificationProvider } from "./components/Notifications";
import { UninstallWizard } from "./features/uninstall/UninstallWizard";
import "./i18n";

// A desktop application: no browser context menu, except where text is edited.
document.addEventListener("contextmenu", (e) => {
  const target = e.target as HTMLElement | null;
  if (!target?.closest("input, textarea, [contenteditable='true']")) e.preventDefault();
});

function render(): void {
  const root = document.getElementById("root");
  if (!root) return;
  createRoot(root).render(
    <StrictMode>
      {/* "Uninstall KVM Studio" opens a window on this page alone. */}
      {new URLSearchParams(window.location.search).get("page") === "uninstall" ? (
        <NotificationProvider>
          <UninstallWizard />
        </NotificationProvider>
      ) : (
        <Gate />
      )}
    </StrictMode>,
  );
}

// A browser link carries a single-use code, traded for the token first.
void captureToken().finally(render);
