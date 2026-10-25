import { defineConfig } from "@playwright/test";

// Interface tests against the built frontend and a backend on test:///default.
// The backend runs from the repository virtual environment unless PYTHON is set.
const port = 60190;
const python = process.env.PYTHON ?? "../.venv/bin/python";

export default defineConfig({
  testDir: "e2e",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1280, height: 800 },
  },
  webServer: {
    command: `${python} e2e/serve.py ${port}`,
    url: `http://127.0.0.1:${port}/`,
    reuseExistingServer: false,
  },
});
