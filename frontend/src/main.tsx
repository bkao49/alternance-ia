import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { api as realApi, createApi } from "./api/client";
import { ApiContext } from "./api/context";
import App from "./App";
import "./theme/tokens.css";
import "./styles.css";

async function start() {
  let api = realApi;
  // Le faux backend n'est chargé qu'en mode démonstration : cette branche est supprimée du build
  // de production, donc ni le code de démonstration ni son mot de passe n'y sont publiés.
  if (import.meta.env.MODE === "mock") {
    const { createMockFetch } = await import("./mock/mockFetch");
    api = createApi(createMockFetch());
  }

  createRoot(document.getElementById("root") as HTMLElement).render(
    <StrictMode>
      <ApiContext.Provider value={api}>
        <App />
      </ApiContext.Provider>
    </StrictMode>,
  );
}

void start();
