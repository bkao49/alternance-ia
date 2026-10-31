import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { failure, requests, signedInApp } from "./test/helpers";

async function openOffers() {
  const user = await signedInApp();
  await user.click(within(screen.getByRole("navigation", { name: "Navigation principale" })).getByRole("link", { name: "Offres" }));
  await screen.findByRole("list", { name: "Offres pertinentes" });
  return user;
}

const rows = () => within(screen.getByRole("list", { name: "Offres pertinentes" })).getAllByRole("listitem");

describe("écran des offres", () => {
  beforeEach(() => {
    window.location.hash = "";
  });

  it("liste les offres pertinentes par score, avec contrat, explication et lien d'origine", async () => {
    await openOffers();
    expect(screen.getByRole("heading", { level: 1, name: "10 offres pertinentes" })).toBeInTheDocument();
    expect(rows()).toHaveLength(10);
    const first = rows()[0] as HTMLElement;
    expect(first).toHaveTextContent("Machine Learning");
    expect(first).toHaveTextContent("Alternance");
    expect(first).toHaveTextContent("4,6");
    expect(first).toHaveTextContent("sur 5");
    expect(first).toHaveTextContent("Vos projets de classification");
    expect(within(first).getByRole("link", { name: "Voir l'annonce d'origine" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.queryByText(/Peu de recoupements/)).not.toBeInTheDocument(); // sous le seuil de pertinence
  });

  it("filtre par type de contrat", async () => {
    const user = await openOffers();
    await user.click(screen.getByRole("button", { name: "CDI" }));
    await screen.findByRole("heading", { level: 1, name: "2 offres pertinentes" });
    expect(rows()).toHaveLength(2);
    expect(requests.at(-1)?.url).toContain("contract_type=permanent");
    await user.click(screen.getByRole("button", { name: "Autre" }));
    expect(await screen.findByText("Aucune offre pertinente pour ce type de contrat.")).toBeInTheDocument();
  });

  it("prépare une candidature à partir d'une offre sans rien envoyer", async () => {
    const user = await openOffers();
    const row = rows().find((r) => r.textContent?.includes("Nimbus Cloud")) as HTMLElement;
    await user.click(within(row).getByRole("button", { name: /Préparer la candidature/ }));
    expect(await within(row).findByText("Dans vos candidatures")).toBeInTheDocument();
    const post = requests.find((r) => r.method === "POST" && r.url.endsWith("/applications"));
    expect(await post?.json()).toEqual({ offer_id: "offer-extra-1", initial_status: "to_prepare" });
    expect(requests.some((r) => r.url.includes("confirm-sent"))).toBe(false);
  });

  it("n'offre pas de second bouton pour une offre déjà dans les candidatures", async () => {
    await openOffers();
    const row = rows().find((r) => r.textContent?.includes("Globex IA")) as HTMLElement;
    expect(within(row).queryByRole("button")).not.toBeInTheDocument();
    expect(row).toHaveTextContent("Dans vos candidatures");
  });
});

describe("écran des offres, cas limites", () => {
  beforeEach(() => {
    window.location.hash = "";
  });

  it("relance vraiment le chargement après une erreur", async () => {
    let fail = true;
    const user = await signedInApp((request) =>
      fail && request.url.includes("/offers?") && request.url.includes("min_score") ? failure(500, "error", "Erreur serveur") : undefined,
    );
    await user.click(within(screen.getByRole("navigation", { name: "Navigation principale" })).getByRole("link", { name: "Offres" }));
    await user.click(await screen.findByRole("button", { name: "Réessayer" }));
    expect(await screen.findByText(/Chargement des offres impossible/)).toBeInTheDocument();
    fail = false;
    await user.click(screen.getByRole("button", { name: "Réessayer" }));
    expect(await screen.findByRole("list", { name: "Offres pertinentes" })).toBeInTheDocument();
  });
});
