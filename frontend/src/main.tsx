import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { captureToken } from "./api/token";
import { App } from "./app/App";
import "./i18n";
import "./styles/tokens.css";

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
      <App />
    </StrictMode>,
  );
}
