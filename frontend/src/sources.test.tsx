import { screen, within } from "@testing-library/react";
import { act } from "react";
import { beforeEach, describe, expect, it } from "vitest";

import { failure, requests, signedInApp, type Intercept } from "./test/helpers";

beforeEach(() => {
  window.location.hash = "";
  document.cookie = "csrf_token=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
});

async function openSources(intercept?: Intercept) {
  const user = await signedInApp(intercept);
  act(() => {
    window.location.hash = "#sources";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
  await screen.findByRole("heading", { name: "Mes sources" });
  return user;
}

const card = (name: string) => within(screen.getByRole("listitem", { name }));

describe("Mes sources", () => {
  it("liste les sources avec leur état", async () => {
    await openSources();
    expect(await screen.findByText("France Travail")).toBeInTheDocument();
    expect(card("France Travail").getByText("Clé manquante")).toBeInTheDocument();
    expect(card("France Travail").getByLabelText("Activer cette source")).toBeDisabled();
    expect(card("La Bonne Alternance").getByText("Activée")).toBeInTheDocument();
    expect(card("Adzuna").getByText("Bloquée")).toBeInTheDocument();
  });

  it("désactive une source et envoie le contrat", async () => {
    const user = await openSources();
    await screen.findByText("La Bonne Alternance");
    await user.click(card("La Bonne Alternance").getByLabelText("Activer cette source"));
    expect(await card("La Bonne Alternance").findByText("Désactivée")).toBeInTheDocument();
    const put = requests.find((r) => r.method === "PUT" && r.url.endsWith("/sources/lba"));
    expect(await put?.clone().json()).toEqual({ enabled: false, interval_minutes: null });
    expect(put?.headers.get("X-CSRF-Token")).toBeTruthy();
  });

  it("règle la fréquence", async () => {
    const user = await openSources();
    await screen.findByText("La Bonne Alternance");
    await user.selectOptions(card("La Bonne Alternance").getByLabelText("Fréquence de collecte"), "360");
    const put = requests.find((r) => r.method === "PUT");
    expect(await put?.clone().json()).toEqual({ enabled: true, interval_minutes: 360 });
  });

  it("ne réactive une source bloquée qu'après confirmation explicite", async () => {
    const user = await openSources();
    await screen.findByText("Adzuna");
    expect(card("Adzuna").getByRole("alert")).toHaveTextContent("blocage détecté (403)");
    expect(card("Adzuna").queryByLabelText("Activer cette source")).not.toBeInTheDocument();
    await user.click(card("Adzuna").getByRole("button", { name: /Réactiver malgré le blocage/ }));
    expect(requests.some((r) => r.method === "PUT")).toBe(false); // rien n'est parti sans confirmation
    await user.click(card("Adzuna").getByRole("button", { name: /Je comprends/ }));
    expect(await card("Adzuna").findByText("Activée")).toBeInTheDocument();
    const put = requests.find((r) => r.method === "PUT");
    expect(await put?.clone().json()).toEqual({ enabled: true, interval_minutes: null, confirm_unblock: true });
  });

  it("affiche l'erreur du serveur sous la source", async () => {
    const user = await openSources((request) =>
      request.method === "PUT" ? failure(409, "source_not_configured", "La clé de cette source n'est pas configurée.") : undefined,
    );
    await screen.findByText("La Bonne Alternance");
    await user.click(card("La Bonne Alternance").getByLabelText("Activer cette source"));
    expect(await card("La Bonne Alternance").findByRole("alert")).toHaveTextContent("n'est pas configurée");
  });
});
