import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The bundle lands inside the Python package so one process serves the API and
// the UI. In development, /v1 and /mcp are proxied to `agw serve`.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/agw/web/dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      "/v1": "http://127.0.0.1:8080",
      "/mcp": "http://127.0.0.1:8080",
      "/healthz": "http://127.0.0.1:8080",
    },
  },
});
