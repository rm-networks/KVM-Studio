import { readFileSync } from "node:fs";

import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

// The product name lives in one place, next to the backend version.
const appName = /^APP_NAME = "(.+)"$/m.exec(
  readFileSync(new URL("../backend/kvmstudio/__init__.py", import.meta.url), "utf-8"),
)?.[1];
if (!appName) throw new Error("APP_NAME not found in backend/kvmstudio/__init__.py");

export default defineConfig(({ mode }) => {
  // In development the API runs separately: kvm-studio --mode web --reload
  const env = loadEnv(mode, ".", "KVMSTUDIO_");
  const backend = env.KVMSTUDIO_BACKEND ?? "http://127.0.0.1:60080";

  return {
    plugins: [
      react(),
      {
        name: "app-name",
        transformIndexHtml: (html: string) => html.replaceAll("%APP_NAME%", appName),
      },
    ],
    define: { __APP_NAME__: JSON.stringify(appName) },
    server: {
      host: "127.0.0.1",
      proxy: { "/api": backend },
    },
    build: {
      target: "es2022",
    },
    test: {
      environment: "jsdom",
      setupFiles: ["src/test/setup.ts"],
    },
  };
});
