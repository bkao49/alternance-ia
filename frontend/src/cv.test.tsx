import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { act } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { checkCvFile } from "./components/CvImport";
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

const fictionalCv = () => new File(["contenu fictif"], "cv-fictif.pdf", { type: "application/pdf" });
const fileInput = () => screen.getByTestId("cv-file") as HTMLInputElement;
const SLOW = { timeout: 6000 };

describe("Import du CV", () => {
  it("vérifie le fichier avant l'envoi", () => {
    expect(checkCvFile({ name: "cv.pdf", size: 10 })).toBeNull();
    expect(checkCvFile({ name: "CV.DOCX", size: 10 })).toBeNull();
    expect(checkCvFile({ name: "cv.txt", size: 10 })).toMatch(/PDF et DOCX/);
    expect(checkCvFile({ name: "cv.pdf", size: 6 * 1024 * 1024 })).toMatch(/5 Mo/);
    expect(checkCvFile({ name: "cv.pdf", size: 0 })).toMatch(/vide/);
  });

  it("annonce l'état vide et la zone de dépôt au clavier", async () => {
    await openProfile();
    expect(await screen.findByText("Aucun CV déposé.")).toBeInTheDocument();
    const zone = screen.getByRole("button", { name: /Déposer un CV/ });
    expect(zone).toHaveAttribute("tabindex", "0");
  });

  it("refuse un mauvais type sans rien envoyer", async () => {
    await openProfile();
    await screen.findByText("Aucun CV déposé.");
    fireEvent.change(fileInput(), { target: { files: [new File(["x"], "notes.txt", { type: "text/plain" })] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Seuls les fichiers PDF et DOCX");
    expect(requests.some((r) => r.method === "POST" && r.url.endsWith("/profile/cv"))).toBe(false);
  });

  it("dépose un CV, montre la progression puis les faits à valider", async () => {
    const user = await openProfile();
    await screen.findByText("Aucun CV déposé.");
    await user.upload(fileInput(), fictionalCv());
    expect(await screen.findByRole("progressbar", { name: /Lecture du CV/ })).toBeInTheDocument();

    const section = await screen.findByRole("region", { name: /À valider \(4\)/ }, SLOW);
    expect(within(section).getAllByRole("listitem")).toHaveLength(4);
    expect(screen.getAllByText(/4 fait\(s\) proposé\(s\) à relire/).length).toBeGreaterThan(0);
    const upload = requests.find((r) => r.method === "POST" && r.url.endsWith("/profile/cv"));
    expect(upload?.headers.get("content-type")).toMatch(/multipart\/form-data/);

    await user.click(within(section).getByRole("button", { name: /Valider : Python/ }));
    await screen.findByRole("region", { name: /À valider \(3\)/ });
    await user.click(screen.getByRole("button", { name: /Rejeter : Anglais/ }));
    await screen.findByRole("region", { name: /À valider \(2\)/ });
    expect(within(screen.getAllByRole("list")[1] as HTMLElement).getByText("Python")).toBeInTheDocument();
    expect(requests.filter((r) => r.url.includes("/validate") || r.url.includes("/reject"))).toHaveLength(2);
  }, 15000);

  it("modifie un fait proposé sans le valider", async () => {
    const user = await openProfile();
    await screen.findByText("Aucun CV déposé.");
    await user.upload(fileInput(), fictionalCv());
    await screen.findByRole("region", { name: /À valider \(4\)/ }, SLOW);
    await user.click(screen.getByRole("button", { name: /Modifier : Anglais/ }));
    const dialog = await screen.findByRole("dialog");
    const text = within(dialog).getByLabelText(/Le fait/);
    await user.clear(text);
    await user.type(text, "Anglais courant");
    await user.click(within(dialog).getByRole("button", { name: "Enregistrer" }));
    expect(await screen.findByText("Anglais courant")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: /À valider \(4\)/ })).toBeInTheDocument();
  }, 15000);

  it("supprime le CV et ses faits après confirmation", async () => {
    const user = await openProfile();
    await screen.findByText("Aucun CV déposé.");
    await user.upload(fileInput(), fictionalCv());
    await screen.findByRole("region", { name: /À valider \(4\)/ }, SLOW);

    await user.click(screen.getByRole("button", { name: "Supprimer mon CV et mes faits" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Annuler" }));
    expect(requests.some((r) => r.method === "DELETE")).toBe(false);

    await user.click(screen.getByRole("button", { name: "Supprimer mon CV et mes faits" }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Supprimer définitivement" }));
    expect(await screen.findByText("Aucun CV déposé.")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("region", { name: /À valider/ })).toBeNull());
    expect(requests.some((r) => r.method === "DELETE" && r.url.endsWith("/profile/cv"))).toBe(true);
  }, 15000);

  it("affiche en français le refus du serveur", async () => {
    const user = await openProfile((request) =>
      request.method === "POST" && request.url.endsWith("/profile/cv")
        ? failure(415, "unsupported_file", "Seuls les PDF et DOCX sans contenu actif sont acceptés")
        : undefined,
    );
    await screen.findByText("Aucun CV déposé.");
    await user.upload(fileInput(), fictionalCv());
    expect(await screen.findByRole("alert")).toHaveTextContent("sans contenu actif");
  });

  it("explique un échec de lecture", async () => {
    const failed = {
      id: "cv-1", original_name: "scan.pdf", file_type: "pdf", size_bytes: 10, status: "failed",
      error_code: "no_text", facts_proposed: 0, created_at: "2026-10-31T10:00:00Z",
    };
    await openProfile((request) =>
      request.method === "GET" && request.url.endsWith("/profile/cv")
        ? new Response(JSON.stringify(failed), { status: 200, headers: { "Content-Type": "application/json" } })
        : undefined,
    );
    expect(await screen.findByText(/Aucun texte lisible/)).toBeInTheDocument();
    expect(screen.getByText("scan.pdf")).toBeInTheDocument();
  });

  it("n'interprète jamais le texte d'un fait comme du HTML", async () => {
    const hostile = [{
      id: "f1", kind: "skill", text: "<img src=x onerror=alert(1)>", start_date: null, end_date: null,
      technologies: [], source: "CV", created_at: "2026-10-31T10:00:00Z", status: "proposed",
    }];
    await openProfile((request) =>
      request.method === "GET" && request.url.endsWith("/profile/facts")
        ? new Response(JSON.stringify(hostile), { status: 200, headers: { "Content-Type": "application/json" } })
        : undefined,
    );
    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(document.querySelector("img[src='x']")).toBeNull();
  });
});
