import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ProfileFact } from "./api/types";
import { requests, signedInApp } from "./test/helpers";

// Faits entièrement fictifs.
const fact = (id: string, kind: ProfileFact["kind"], text: string, technologies: string[] = []): ProfileFact => ({
  id, kind, text, technologies, start_date: null, end_date: null, source: "saisie manuelle", status: "validated", created_at: "2026-01-01T00:00:00Z",
});
const FACTS = [
  fact("f1", "experience", "Stage de data analyst chez Acme (fictif)", ["Python"]),
  fact("f2", "education", "Master Data Science, Université Imaginaire (fictif)"),
  fact("f3", "skill", "SQL", ["SQL"]),
];

async function openPreparation(facts: ProfileFact[] = FACTS) {
  const user = await signedInApp(undefined, { facts });
  window.location.hash = "#preparer/offer-extra-1";
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  await screen.findByRole("heading", { level: 1, name: "Préparer la candidature" });
  await screen.findByRole("button", { name: "Générer" });
  return user;
}

const texts = () => screen.getAllByRole("textbox").map((box) => (box as HTMLTextAreaElement).value);

describe("préparation d'une candidature", () => {
  beforeEach(() => {
    window.location.hash = "";
  });

  it("génère un CV dont chaque ligne cite ses faits, contrôle factuel vert", async () => {
    const user = await openPreparation();
    await user.click(screen.getByRole("button", { name: "Générer" }));
    expect(await screen.findByText(/Contrôle factuel : tout est justifié/)).toBeInTheDocument();
    expect(texts()).toContain("Stage de data analyst chez Acme (fictif)");
    expect(screen.getAllByText(/Fait : Stage de data analyst/).length).toBeGreaterThan(0);
    expect(screen.getAllByText("Identique au CV maître").length).toBeGreaterThan(0);
    const post = requests.find((r) => r.method === "POST" && r.url.endsWith("/documents/generate"));
    expect(await post?.json()).toEqual({ kind: "cv", offer_id: "offer-extra-1" });
    expect(requests.some((r) => r.url.includes("confirm-sent"))).toBe(false); // rien n'est envoyé
  });

  it("refuse de générer sans assez de faits validés et renvoie vers le profil", async () => {
    const user = await openPreparation([FACTS[0] as ProfileFact]);
    await user.click(screen.getByRole("button", { name: "Générer" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/au moins 3 faits validés.*Mon profil/);
  });

  it("modifie, réordonne et retire des lignes, enregistre une nouvelle version et revient en arrière", async () => {
    const user = await openPreparation();
    await user.click(screen.getByRole("button", { name: "Générer" }));
    await screen.findByText(/tout est justifié/);
    const before = texts();
    await user.click(screen.getAllByRole("button", { name: /^Retirer : / })[0] as HTMLElement);
    expect(texts().length).toBe(before.length - 1);
    expect(screen.getByText(/Modifications non enregistrées/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Exporter en PDF" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Enregistrer mes modifications" }));
    const versions = await screen.findByRole("region", { name: "Versions" });
    expect(await within(versions).findByText(/Version 2/)).toBeInTheDocument();
    await user.click(within(versions).getByRole("button", { name: "Restaurer la version 1" }));
    expect(await within(versions).findByText(/Version 3/)).toBeInTheDocument();
    expect(texts()).toEqual(before);
  });

  it("une ligne ajoutée à la main devient un fait à valider, rejetée tant qu'il ne l'est pas", async () => {
    const user = await openPreparation();
    await user.click(screen.getByRole("button", { name: "Générer" }));
    await screen.findByText(/tout est justifié/);
    await user.click(screen.getByRole("button", { name: /^Ajouter une ligne à « Formation »/ }));
    const added = screen.getByRole("textbox", { name: /^Texte : Formation, ligne 2/ });
    await user.type(added, "Maîtrise de Kubernetes");
    expect(screen.getByText(/deviendra un fait à valider/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Enregistrer mes modifications" }));
    expect(await screen.findByText(/Contrôle factuel : 1 ligne rejetée/)).toBeInTheDocument();
    expect(screen.getAllByText(/n'est pas encore validé/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Exporter en PDF" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Valider ce fait" }));
    expect(await screen.findByText(/Contrôle factuel : tout est justifié/)).toBeInTheDocument(); // validé par l'utilisateur lui-même
  });

  it("exporte le PDF quand le contrôle est vert et propose la relecture par l'IA", async () => {
    const create = vi.fn(() => "blob:fictif");
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    const user = await openPreparation();
    await user.click(screen.getByRole("button", { name: "Générer" }));
    await screen.findByText(/tout est justifié/);
    await user.click(screen.getByRole("button", { name: "Faire relire par l'IA" }));
    expect(await screen.findByText(/Relu aussi par l'IA/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Exporter en PDF" }));
    await vi.waitFor(() => expect(click).toHaveBeenCalled());
    expect(requests.some((r) => r.url.endsWith("/pdf"))).toBe(true);
    click.mockRestore();
  });

  it("n'exporte pas un texte que la relecture par l'IA vient de rejeter", async () => {
    const rejected = { ok: false, verified: true, issues: [{ section: 0, bullet: 0, code: "verifier_rejected", message: "Ajout non écrit" }] };
    const user = await signedInApp(
      (request) => (request.url.endsWith("/check") ? new Response(JSON.stringify(rejected), { status: 200, headers: { "Content-Type": "application/json" } }) : undefined),
      { facts: FACTS },
    );
    window.location.hash = "#preparer/offer-extra-1";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    await user.click(await screen.findByRole("button", { name: "Générer" }));
    await screen.findByText(/tout est justifié/);
    await user.click(screen.getByRole("button", { name: "Faire relire par l'IA" }));
    expect(await screen.findByText(/1 ligne rejetée/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Exporter en PDF" })).toBeDisabled();
  });

  it("propose la lettre et le CV général", async () => {
    const user = await openPreparation();
    await user.click(screen.getByRole("button", { name: "Lettre de motivation" }));
    await user.click(await screen.findByRole("button", { name: "Générer" }));
    expect(await screen.findByRole("region", { name: "Lettre" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "CV général amélioré" }));
    await user.click(await screen.findByRole("button", { name: "Générer" }));
    await screen.findByRole("region", { name: "Expérience" });
    const bodies = await Promise.all(requests.filter((r) => r.url.endsWith("/documents/generate")).map((r) => r.json()));
    expect(bodies).toEqual([{ kind: "cover_letter", offer_id: "offer-extra-1" }, { kind: "cv", offer_id: null }]);
  });
});
