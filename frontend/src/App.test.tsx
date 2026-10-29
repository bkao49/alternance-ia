import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import {
  bodyRows,
  counter,
  firstCompany,
  renderApp,
  signedInApp,
  signIn,
  validateMove,
  type User,
} from "./test/helpers";

beforeEach(() => {
  document.cookie = "csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
});

describe("connexion", () => {
  it("refuse un mauvais mot de passe sans révéler de détail", async () => {
    const user = renderApp();
    await signIn(user, "mauvais");
    expect(await screen.findByRole("alert")).toHaveTextContent("Identifiants invalides");
    expect(screen.queryByRole("heading", { name: "Candidatures" })).not.toBeInTheDocument();
  });

  it("affiche le tableau de bord puis permet de se déconnecter", async () => {
    const user = await signedInApp();
    await user.click(screen.getByRole("button", { name: "Se déconnecter" }));
    expect(await screen.findByRole("button", { name: "Se connecter" })).toBeInTheDocument();
  });
});

describe("accueil", () => {
  it("salue l'utilisateur et résume les chiffres réels", async () => {
    await signedInApp();
    expect(screen.getByRole("heading", { level: 1, name: "Bonjour Demo." })).toBeInTheDocument();
    expect(screen.getByText(/14 offres pertinentes à regarder\. Une candidature attend votre validation\./)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "14 offres pertinentes" })).toBeInTheDocument();
  });

  it("n'invente aucune activité du bot hors démonstration", async () => {
    await signedInApp();
    const bot = screen.getByRole("region", { name: "Le bot" });
    expect(bot).toHaveTextContent("Aucune collecte pour l'instant");
    expect(within(bot).queryByRole("list")).not.toBeInTheDocument();
  });

  it("garde l'écran des offres annoncé mais inactif tant qu'il n'existe pas", async () => {
    await signedInApp();
    const nav = screen.getByRole("navigation", { name: "Navigation principale" });
    expect(within(nav).getByRole("link", { name: "Candidatures" })).toHaveAttribute("href", "#candidatures");
    expect(within(nav).queryByRole("link", { name: /Offres/ })).not.toBeInTheDocument();
    expect(within(nav).getByText("bientôt")).toBeInTheDocument();
  });
});

describe("chiffres clés", () => {
  it("affiche les compteurs et les taux de conversion", async () => {
    await signedInApp();
    expect(counter("Entretiens")).toHaveTextContent("1");
    expect(counter("Envoyées")).toHaveTextContent("5");
    expect(counter("Détectées")).toHaveTextContent("42");
    expect(screen.getByText("Envoyée → entretien").parentElement).toHaveTextContent("20 %");
  });
});

describe("vue tableau", () => {
  it("liste toutes les candidatures et se trie par colonne", async () => {
    const user = await signedInApp();
    expect(bodyRows()).toHaveLength(12);

    await user.click(screen.getByRole("button", { name: /Entreprise/ }));
    expect(screen.getByRole("columnheader", { name: /Entreprise/ })).toHaveAttribute("aria-sort", "ascending");
    expect(firstCompany()).toBe("Acme Analytics");

    await user.click(screen.getByRole("button", { name: /Entreprise/ }));
    expect(screen.getByRole("columnheader", { name: /Entreprise/ })).toHaveAttribute("aria-sort", "descending");
    expect(firstCompany()).toBe("Wayne Énergie");
  });

  it("filtre par recherche et par statut", async () => {
    const user = await signedInApp();
    await user.type(screen.getByLabelText("Rechercher une candidature"), "data engineer");
    expect(bodyRows()).toHaveLength(2);

    await user.clear(screen.getByLabelText("Rechercher une candidature"));
    await user.selectOptions(screen.getByLabelText("Filtrer par statut"), "Entretien");
    expect(bodyRows()).toHaveLength(1);
    expect(firstCompany()).toBe("Stark Mobilité");

    await user.type(screen.getByLabelText("Rechercher une candidature"), "introuvable");
    expect(screen.getByText(/Aucune candidature ne correspond/)).toBeInTheDocument();
  });
});

describe("vue Kanban", () => {
  async function openKanban(user: User) {
    await user.click(screen.getByRole("button", { name: "Kanban" }));
    return screen.getByRole("list", { name: "Candidatures par statut" });
  }
  const column = (board: HTMLElement, name: string | RegExp) => within(board).getByRole("listitem", { name });

  it("range les candidatures dans une colonne par statut", async () => {
    const user = await signedInApp();
    const board = await openKanban(user);
    expect(board.querySelectorAll(":scope > li")).toHaveLength(10);
    expect(within(column(board, /Détectée/)).getAllByRole("button", { name: /^(Cyberdyne Vision|Soylent Foods)$/ })).toHaveLength(2);
  });

  it("déplace une carte d'une colonne à l'autre, au clavier comme à la souris", async () => {
    const user = await signedInApp();
    const board = await openKanban(user);
    await user.selectOptions(within(board).getByLabelText("Déplacer Cyberdyne Vision vers…"), "Analysée");
    await user.click(validateMove("Cyberdyne Vision"));

    expect(await within(column(board, /Analysée/)).findByRole("button", { name: "Cyberdyne Vision" })).toBeInTheDocument();
    expect(within(column(board, /Détectée/)).queryByRole("button", { name: "Cyberdyne Vision" })).not.toBeInTheDocument();
  });
});

describe("parcours : créer une candidature puis changer son statut", () => {
  it("ajoute une candidature, la déplace, et garde l'historique", async () => {
    const user = await signedInApp();
    await user.click(screen.getByRole("button", { name: "Nouvelle candidature" }));
    const form = screen.getByRole("dialog", { name: "Nouvelle candidature" });
    expect(within(form).getByRole("button", { name: "Ajouter" })).toBeDisabled();
    await user.type(within(form).getByLabelText("Entreprise"), "Zorg Industries");
    await user.type(within(form).getByLabelText("Poste"), "Alternant Data Ops");
    await user.click(within(form).getByRole("button", { name: "Ajouter" }));

    expect(await screen.findByRole("button", { name: "Zorg Industries" })).toBeInTheDocument();
    expect(bodyRows()).toHaveLength(13);

    await user.selectOptions(screen.getByLabelText("Déplacer Zorg Industries vers…"), "Entretien");
    await user.click(validateMove("Zorg Industries"));
    const row = (await screen.findByRole("button", { name: "Zorg Industries" })).closest("tr") as HTMLElement;
    await within(row).findByText("Entretien");

    await user.click(within(row).getByRole("button", { name: "Zorg Industries" }));
    const dialog = await screen.findByRole("dialog", { name: "Zorg Industries" });
    const history = await within(dialog).findByRole("list");
    expect(within(history).getAllByRole("listitem")).toHaveLength(2);
    expect(history).toHaveTextContent("À préparer → Entretien");
  });
});

describe("règle : « Envoyée » seulement par confirmation humaine", () => {
  it("ne propose jamais « Envoyée » dans les menus de déplacement", async () => {
    await signedInApp();
    for (const select of screen.getAllByLabelText(/^Déplacer .* vers…$/)) {
      expect(within(select).queryByRole("option", { name: "Envoyée" })).not.toBeInTheDocument();
    }
  });

  it("exige de cocher la confirmation avant de marquer une candidature comme envoyée", async () => {
    const user = await signedInApp();
    await user.click(screen.getByRole("button", { name: "Initech Data" }));
    const dialog = await screen.findByRole("dialog", { name: "Initech Data" });

    await user.click(within(dialog).getByRole("button", { name: "J'ai envoyé cette candidature" }));
    const confirm = within(dialog).getByRole("button", { name: "Marquer comme envoyée" });
    expect(confirm).toBeDisabled();

    await user.click(within(dialog).getByLabelText("Je confirme avoir envoyé moi-même cette candidature"));
    expect(confirm).toBeEnabled();
    await user.click(confirm);

    expect(await within(dialog).findByText(/envoyée le/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "J'ai envoyé cette candidature" })).not.toBeInTheDocument();
    expect(counter("Envoyées")).toHaveTextContent("6");
  });
});

describe("clavier", () => {
  it("ouvre la fiche d'une candidature avec la touche Entrée", async () => {
    const user = await signedInApp();
    const link = screen.getByRole("button", { name: "Acme Analytics" });
    link.focus();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("dialog", { name: "Acme Analytics" })).toBeInTheDocument();
  });

  it("atteint le changement de vue par la touche Tab", async () => {
    const user = await signedInApp();
    const onKanban = () => document.activeElement?.tagName === "BUTTON" && document.activeElement.textContent === "Kanban";
    for (let i = 0; i < 12 && !onKanban(); i += 1) await user.tab();
    expect(onKanban()).toBe(true);
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Kanban" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("list", { name: "Candidatures par statut" })).toBeInTheDocument();
  });
});
