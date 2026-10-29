import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

import { APP_NAME } from "./src/brand";

// En développement, /api est relayé vers le backend local (docker compose, port 8100 par défaut).
export default defineConfig({
  plugins: [
    react(),
    // Le titre de l'onglet reprend APP_NAME : le nom du produit ne s'écrit qu'à un seul endroit.
    { name: "app-name", transformIndexHtml: (html) => html.replace("%APP_NAME%", APP_NAME) },
  ],
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
