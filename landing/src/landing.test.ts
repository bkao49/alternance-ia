import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { initialTheme } from "./theme";
import { redEvery, waveHeight } from "./wave";

const html = readFileSync(resolve(process.cwd(), "index.html"), "utf-8");
const css = readFileSync(resolve(process.cwd(), "src/styles.css"), "utf-8");

describe("contenu", () => {
  it("raconte les six étapes, pour tous les métiers", () => {
    expect(html.match(/data-step/g)).toHaveLength(6);
    expect(html).toContain("Pour tous les métiers et tous les contrats");
    expect(html).not.toMatch(/Data et IA|Data \/ IA|Piste/);
  });

  it("ne promet aucun envoi automatique", () => {
    expect(html).toContain("n'envoie jamais rien à ta place");
    expect(html).toContain("Aucun envoi automatique");
  });

  it("n'utilise pas de point-virgule dans les textes", () => {
    const text = html.replace(/<script[\s\S]*?<\/script>/g, "").replace(/<[^>]+>/g, " ");
    expect(text).not.toContain(" ;");
  });
});

describe("page", () => {
  it("ne charge aucune ressource externe ni traceur", () => {
    expect(html).not.toMatch(/fonts\.googleapis|googletagmanager|analytics|<iframe|<video|cloudfront/i);
    expect(css).not.toMatch(/url\(["']?https?:/);
  });

  it("prévoit le mouvement réduit et le thème sombre du système", () => {
    expect(css).toContain("prefers-reduced-motion: reduce");
    expect(css).toContain("prefers-color-scheme: dark");
  });
});

describe("initialTheme", () => {
  it("garde le choix mémorisé", () => {
    expect(initialTheme("dark", false)).toBe("dark");
    expect(initialTheme("light", true)).toBe("light");
  });

  it("suit le système, sinon clair", () => {
    expect(initialTheme(null, true)).toBe("dark");
    expect(initialTheme(null, false)).toBe("light");
    expect(initialTheme("bleu", false)).toBe("light");
  });
});

describe("vague", () => {
  it("reste dans une amplitude bornée", () => {
    for (let x = -2; x <= 2; x += 0.25) for (let t = 0; t < 20; t += 1.5) expect(Math.abs(waveHeight(x, 0.5, t))).toBeLessThanOrEqual(1.15);
  });

  it("a de plus en plus de points rouges vers le bas de la page", () => {
    expect(redEvery(0)).toBe(97);
    expect(redEvery(1)).toBe(23);
    expect(redEvery(0.5)).toBeLessThan(redEvery(0));
  });
});
