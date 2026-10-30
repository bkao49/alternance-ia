import { screen } from "@testing-library/react";
import { act } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { toList } from "./components/CriteriaPage";
import { failure, requests, signedInApp, type Intercept } from "./test/helpers";

beforeEach(() => {
  window.location.hash = "";
  document.cookie = "csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
});

function go(hash: string) {
  act(() => {
    window.location.hash = hash;
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
}

async function openCriteria(intercept?: Intercept) {
  const user = await signedInApp(intercept);
  go("#criteres");
  await screen.findByRole("heading", { name: "Mes critères" });
  return user;
}

describe("Mes critères", () => {
  it("nettoie les listes saisies", () => {
    expect(toList(" data \n\ndata\n ml ")).toEqual(["data", "ml"]);
  });

  it("envoie le corps complet du contrat", async () => {
    const user = await openCriteria();
    await user.type(screen.getByLabelText(/Métiers ou mots-clés/), "data analyst{Enter}machine learning{Enter}data analyst");
    await user.click(screen.getByRole("button", { name: "Ajouter un lieu" }));
    await user.type(screen.getByLabelText("Ville ou région"), "Lyon");
    await user.click(screen.getByLabelText("Alternance"));
    await user.click(screen.getByLabelText(/Télétravail/));
    await user.type(screen.getByLabelText(/Durée/), "12");
    await user.selectOptions(screen.getByLabelText("Niveau d'études"), "bac_plus_5");
    await user.type(screen.getByLabelText(/Mots à exclure/), "commercial");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(await screen.findByText("Critères enregistrés.")).toBeInTheDocument();
    const put = requests.find((r) => r.method === "PUT");
    expect(await put?.clone().json()).toEqual({
      keywords: ["data analyst", "machine learning"],
      locations: [{ label: "Lyon", radius_km: 30 }],
      remote_accepted: true,
      contract_types: ["apprenticeship"],
      start_date: null,
      duration_months: 12,
      alternance_rhythm: null,
      education_level: "bac_plus_5",
      min_salary_eur: null,
      excluded_keywords: ["commercial"],
    });
  });

  it("retire un lieu et ne renvoie pas deux lieux identiques", async () => {
    const user = await openCriteria();
    for (const city of ["Lyon", "Lyon", "Nantes"]) {
      await user.click(screen.getByRole("button", { name: "Ajouter un lieu" }));
      const fields = screen.getAllByLabelText(/Ville ou région/);
      await user.type(fields[fields.length - 1] as HTMLElement, city);
    }
    await user.click(screen.getByRole("button", { name: "Retirer le lieu 3 : Nantes" }));
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));
    await screen.findByText("Critères enregistrés.");
    const put = requests.find((r) => r.method === "PUT");
    const body = (await put?.clone().json()) as { locations: unknown };
    expect(body.locations).toEqual([{ label: "Lyon", radius_km: 30 }]);
  });

  it("montre l'erreur du serveur sans perdre la saisie", async () => {
    const user = await openCriteria((request) =>
      request.method === "PUT" ? failure(422, "validation_error", "Données invalides") : undefined,
    );
    await user.type(screen.getByLabelText(/Mots à exclure/), "commercial");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Données invalides");
    expect(screen.getByLabelText(/Mots à exclure/)).toHaveValue("commercial");
  });

  it("signale l'échec du chargement avec le titre de la page", async () => {
    await openCriteria((request) =>
      request.method === "GET" && request.url.endsWith("/preferences") ? failure(500, "error", "Service indisponible") : undefined,
    ).catch(() => undefined);
    expect(await screen.findByRole("alert")).toHaveTextContent("Service indisponible");
    expect(screen.getByRole("heading", { name: "Mes critères" })).toBeInTheDocument();
  });

  it("revient aux candidatures depuis « Mes critères »", async () => {
    await openCriteria();
    go("#candidatures");
    expect(await screen.findByRole("heading", { name: "Candidatures" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Accueil" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("heading", { name: "Mes critères" })).not.toBeInTheDocument();
  });
});
