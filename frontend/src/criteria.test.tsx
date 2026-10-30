import { screen } from "@testing-library/react";
import { act } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { toList } from "./components/CriteriaPage";
import { failure, requests, signedInApp, type Intercept } from "./test/helpers";

beforeEach(() => {
  window.location.hash = "";
  document.cookie = "csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
});

async function openCriteria(intercept?: Intercept) {
  const user = await signedInApp(intercept);
  act(() => {
    window.location.hash = "#criteres";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
  await screen.findByRole("heading", { name: "Mes critères" });
  return user;
}

describe("Mes critères", () => {
  it("nettoie les listes saisies", () => {
    expect(toList(" data \n\ndata\n ml ")).toEqual(["data", "ml"]);
  });

  it("enregistre la saisie dans le format du contrat", async () => {
    const user = await openCriteria();
    await user.type(screen.getByLabelText(/Métiers ou mots-clés/), "data analyst{Enter}machine learning");
    await user.click(screen.getByRole("button", { name: "Ajouter un lieu" }));
    await user.type(screen.getByLabelText("Ville ou région"), "Lyon");
    await user.click(screen.getByLabelText("Alternance"));
    await user.selectOptions(screen.getByLabelText("Niveau d'études"), "bac_plus_5");
    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    expect(await screen.findByText("Critères enregistrés.")).toBeInTheDocument();
    const put = requests.find((r) => r.method === "PUT");
    expect(await put?.clone().json()).toMatchObject({
      keywords: ["data analyst", "machine learning"],
      locations: [{ label: "Lyon", radius_km: 30 }],
      contract_types: ["apprenticeship"],
      education_level: "bac_plus_5",
      start_date: null,
      min_salary_eur: null,
    });
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
});
