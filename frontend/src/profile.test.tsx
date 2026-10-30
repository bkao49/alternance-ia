import { screen, within } from "@testing-library/react";
import { act } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { toTechnologies } from "./components/ProfilePage";
import { failure, requests, signedInApp, type Intercept } from "./test/helpers";

beforeEach(() => {
  window.location.hash = "";
  document.cookie = "csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
});

async function openProfile(intercept?: Intercept) {
  const user = await signedInApp(intercept);
  act(() => {
    window.location.hash = "#profil";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
  await screen.findByRole("heading", { name: "Mon profil" });
  return user;
}

describe("Mon profil", () => {
  it("nettoie les technologies", () => {
    expect(toTechnologies(" Python, SQL,, Python\nR ")).toEqual(["Python", "SQL", "R"]);
  });

  it("annonce l'état vide", async () => {
    await openProfile();
    expect(await screen.findByText(/Aucun fait pour l'instant/)).toBeInTheDocument();
  });

  it("ajoute, modifie puis supprime un fait", async () => {
    const user = await openProfile();
    await user.click(screen.getByRole("button", { name: "Ajouter un fait" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Le fait/), "Stage chez Acme (fictif)");
    await user.type(within(dialog).getByLabelText(/Technologies/), "Python, SQL");
    await user.click(within(dialog).getByRole("button", { name: "Enregistrer" }));

    expect(await screen.findByText("Stage chez Acme (fictif)")).toBeInTheDocument();
    const post = requests.find((r) => r.method === "POST" && r.url.endsWith("/profile/facts"));
    expect(await post?.clone().json()).toEqual({
      kind: "experience",
      text: "Stage chez Acme (fictif)",
      start_date: null,
      end_date: null,
      technologies: ["Python", "SQL"],
      source: null,
    });

    await user.click(screen.getByRole("button", { name: "Modifier : Stage chez Acme (fictif)" }));
    const edit = await screen.findByRole("dialog");
    const field = within(edit).getByLabelText(/Le fait/);
    await user.clear(field);
    await user.type(field, "Alternance chez Acme (fictif)");
    await user.click(within(edit).getByRole("button", { name: "Enregistrer" }));
    expect(await screen.findByText("Alternance chez Acme (fictif)")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Supprimer : Alternance chez Acme (fictif)" }));
    expect(await screen.findByText(/Aucun fait pour l'instant/)).toBeInTheDocument();
  });

  it("refuse une fin avant le début sans appeler le serveur", async () => {
    const user = await openProfile();
    await user.click(screen.getByRole("button", { name: "Ajouter un fait" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Le fait/), "Projet");
    await user.type(within(dialog).getByLabelText(/Début/), "2026-06-01");
    await user.type(within(dialog).getByLabelText(/Fin/), "2026-01-01");
    expect(within(dialog).getByRole("alert")).toHaveTextContent("La fin doit être après le début.");
    expect(within(dialog).getByRole("button", { name: "Enregistrer" })).toBeDisabled();
    expect(requests.some((r) => r.method === "POST" && r.url.endsWith("/profile/facts"))).toBe(false);
  });

  it("garde la saisie quand le serveur refuse", async () => {
    const user = await openProfile((request) =>
      request.method === "POST" && request.url.endsWith("/profile/facts")
        ? failure(409, "too_many_facts", "500 faits au plus")
        : undefined,
    );
    await user.click(screen.getByRole("button", { name: "Ajouter un fait" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Le fait/), "Un fait");
    await user.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("500 faits au plus");
    expect(within(dialog).getByLabelText(/Le fait/)).toHaveValue("Un fait");
  });

  it("affiche le texte d'un fait littéralement, sans l'interpréter comme du HTML", async () => {
    const user = await openProfile();
    await user.click(screen.getByRole("button", { name: "Ajouter un fait" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Le fait/), "<b>gras</b>");
    await user.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
    expect(await screen.findByText("<b>gras</b>")).toBeInTheDocument();
    expect(document.querySelector("li b")).toBeNull();
  });

  it("supprime avec le jeton CSRF et ignore un 404 (déjà supprimé)", async () => {
    const user = await openProfile((request) =>
      request.method === "DELETE" ? failure(404, "not_found", "Fait introuvable") : undefined,
    );
    await user.click(screen.getByRole("button", { name: "Ajouter un fait" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Le fait/), "À retirer");
    await user.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
    await user.click(await screen.findByRole("button", { name: "Supprimer : À retirer" }));
    const request = requests.find((r) => r.method === "DELETE");
    expect(request?.headers.get("X-CSRF-Token")).toBe("demo") // posé par la connexion de démonstration;
    expect(screen.queryByText("Fait introuvable")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Mon profil" })).toHaveFocus();
  });

  it("propose de réessayer quand le chargement échoue", async () => {
    await openProfile((request) =>
      request.method === "GET" && request.url.endsWith("/profile/facts") ? failure(500, "error", "Service indisponible") : undefined,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Service indisponible");
    expect(screen.getByRole("button", { name: "Réessayer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ajouter un fait" })).toBeDisabled();
  });

  it("marque « Mon profil » comme page courante", async () => {
    await openProfile();
    expect(screen.getByRole("link", { name: "Mon profil" })).toHaveAttribute("aria-current", "page");
  });
});
