import type { Plugin } from "vite";
import { defineConfig } from "vitest/config";
import { APP_NAME, APP_URL, REPO_URL } from "./src/brand.ts";

// Le nom provisoire et l'adresse de l'application et du dépôt vivent dans src/brand.ts : on les reporte dans le HTML au build.
function brand(): Plugin {
  return {
    name: "brand",
    transformIndexHtml: (html) => html.replaceAll("__APP_NAME__", APP_NAME).replaceAll("__REPO_URL__", REPO_URL).replaceAll("__APP_URL__", APP_URL),
  };
}

export default defineConfig({
  // Chemins relatifs : la page reste publiable dans un sous-dossier (GitHub Pages, à décider avec le PO).
  base: "./",
  plugins: [brand()],
  build: { target: "es2022", chunkSizeWarningLimit: 600 }, // three.js pèse ~140 Ko compressé, chargé à la demande
  test: { environment: "jsdom" },
});
