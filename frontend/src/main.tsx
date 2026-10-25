// Shared styles first: the screens' own sheets come after them.
import "./styles/tokens.css";
import "./styles/controls.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { captureToken } from "./api/token";
import { App } from "./app/App";
import { NotificationProvider } from "./components/Notifications";
import { UninstallWizard } from "./features/uninstall/UninstallWizard";
import "./i18n";

captureToken();

// A desktop application: no browser context menu, except where text is edited.
document.addEventListener("contextmenu", (e) => {
  const target = e.target as HTMLElement | null;
  if (!target?.closest("input, textarea, [contenteditable='true']")) e.preventDefault();
});

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      {/* "Uninstall KVM Studio" opens a window on this page alone. */}
      {new URLSearchParams(window.location.search).get("page") === "uninstall" ? (
        <NotificationProvider>
          <UninstallWizard />
        </NotificationProvider>
      ) : (
        <App />
      )}
    </StrictMode>,
  );
}
