import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { safeColor } from "./components/common";
import { failure, renderApp, requests, signedInApp, signIn, validateMove } from "./test/helpers";

describe("choix d'un statut au clavier", () => {
  it("ne déplace rien tant qu'on n'a pas validé", async () => {
    const user = await signedInApp();
    const select = screen.getByLabelText("Déplacer Cyberdyne Vision vers…");
    const row = select.closest("tr") as HTMLElement;
    await user.selectOptions(select, "Analysée");
    expect(within(row).getByText("Détectée")).toBeInTheDocument();
    expect(requests.some((r) => r.url.endsWith("/status"))).toBe(false);

    await user.click(validateMove("Cyberdyne Vision"));
    expect(await within(row).findByText("Analysée")).toBeInTheDocument();
  });

  it("garde le bouton de validation inactif sans choix", async () => {
    await signedInApp();
    expect(validateMove("Soylent Foods")).toBeDisabled();
  });
});

describe("texte non fiable", () => {
  it("affiche du HTML venant d'une annonce comme du simple texte", async () => {
    const user = await signedInApp();
    await user.click(screen.getByRole("button", { name: "Nouvelle candidature" }));
    const form = screen.getByRole("dialog", { name: "Nouvelle candidature" });
    const hostile = `<img src=x onerror="alert(1)">`;
    await user.click(within(form).getByLabelText("Entreprise"));
    await user.paste(hostile);
    await user.click(within(form).getByLabelText("Poste"));
    await user.paste("<b>gras</b>");
    await user.click(within(form).getByRole("button", { name: "Ajouter" }));

    expect(await screen.findByRole("button", { name: hostile })).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("b")).toBeNull();
  });

  it("n'injecte une couleur dans le style que si c'est un code hexadécimal", () => {
    expect(safeColor("#12abEF")).toBe("#12abEF");
    expect(safeColor("url(https://example.test/x)")).toBe("#64748b");
    expect(safeColor("red; background:url(x)")).toBe("#64748b");
  });
});

describe("session et erreurs", () => {
  it("ramène à la connexion quand la session expire en cours d'usage", async () => {
    let expired = false;
    const user = await signedInApp(() => (expired ? failure(401, "unauthorized", "Non connecté") : undefined));
    expired = true;
    await user.selectOptions(screen.getByLabelText("Déplacer Cyberdyne Vision vers…"), "Analysée");
    await user.click(validateMove("Cyberdyne Vision"));
    expect(await screen.findByRole("button", { name: "Se connecter" })).toBeInTheDocument();
  });

  it("garde la fenêtre ouverte et la saisie quand la création échoue", async () => {
    const user = await signedInApp((request) =>
      request.method === "POST" && request.url.endsWith("/applications")
        ? failure(422, "validation_error", "Données invalides")
        : undefined,
    );
    await user.click(screen.getByRole("button", { name: "Nouvelle candidature" }));
    const form = screen.getByRole("dialog", { name: "Nouvelle candidature" });
    await user.type(within(form).getByLabelText("Entreprise"), "Zorg");
    await user.type(within(form).getByLabelText("Poste"), "Alternant");
    await user.click(within(form).getByRole("button", { name: "Ajouter" }));

    expect(await within(form).findByRole("alert")).toHaveTextContent("Données invalides");
    expect(within(form).getByLabelText("Entreprise")).toHaveValue("Zorg");
  });

  it("n'annonce pas une déconnexion qui a échoué", async () => {
    const user = await signedInApp((request) =>
      request.url.endsWith("/auth/logout") ? failure(403, "csrf_invalid", "Jeton CSRF invalide") : undefined,
    );
    await user.click(screen.getByRole("button", { name: "Se déconnecter" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Déconnexion impossible");
    expect(screen.getByRole("heading", { name: "Candidatures" })).toBeInTheDocument();
  });

  it("distingue une panne d'un mauvais mot de passe à la connexion", async () => {
    const user = renderApp((request) =>
      request.url.endsWith("/auth/login") ? failure(500, "error", "Erreur serveur") : undefined,
    );
    await signIn(user);
    expect(await screen.findByRole("alert")).toHaveTextContent("Connexion impossible pour le moment");
  });
});

describe("confirmation d'envoi", () => {
  it("n'appelle jamais confirm-sent sans la case cochée, et une seule fois sinon", async () => {
    const user = await signedInApp();
    await user.click(screen.getByRole("button", { name: "Initech Data" }));
    const dialog = await screen.findByRole("dialog", { name: "Initech Data" });
    await user.click(within(dialog).getByRole("button", { name: "J'ai envoyé cette candidature" }));

    await user.click(within(dialog).getByRole("button", { name: "Marquer comme envoyée" })); // inactif
    expect(requests.filter((r) => r.url.endsWith("/confirm-sent"))).toHaveLength(0);

    await user.click(within(dialog).getByLabelText("Je confirme avoir envoyé moi-même cette candidature"));
    await user.dblClick(within(dialog).getByRole("button", { name: "Marquer comme envoyée" }));
    expect(await within(dialog).findByText(/envoyée le/)).toBeInTheDocument();
    expect(requests.filter((r) => r.url.endsWith("/confirm-sent"))).toHaveLength(1);
  });
});
