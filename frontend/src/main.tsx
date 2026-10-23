import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { captureToken } from "./api/token";
import { App } from "./app/App";
import "./i18n";
import "./styles/tokens.css";

captureToken();

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
