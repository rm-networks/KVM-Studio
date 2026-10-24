import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => {
  // In development the API runs separately: kvm-studio --mode web --reload
  const env = loadEnv(mode, ".", "KVMSTUDIO_");
  const backend = env.KVMSTUDIO_BACKEND ?? "http://127.0.0.1:60080";

  return {
    plugins: [react()],
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
