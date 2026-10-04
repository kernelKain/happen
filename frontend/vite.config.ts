import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const backend = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  envDir: "..",
  server: {
    proxy: {
      "/api": backend,
      "/healthz": backend,
    },
  },
  preview: {
    proxy: {
      "/api": backend,
      "/healthz": backend,
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
