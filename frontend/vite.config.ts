import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// En développement, /api est relayé vers le backend local (docker compose, port 8100 par défaut).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8100",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
