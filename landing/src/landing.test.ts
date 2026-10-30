import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { linePath } from "./charts";
import { COLLECTED, SCORE_BINS, SCORE_FROM, SCORE_STEP, total } from "./data";
import { activeStep, storyProgress } from "./story";

const html = readFileSync(resolve(process.cwd(), "index.html"), "utf-8");

describe("chiffres fictifs", () => {
  it("le total affiché correspond aux données du graphique", () => {
    expect(total(COLLECTED)).toBe(1204);
    expect(COLLECTED).toHaveLength(30);
    expect(html).toContain("1&nbsp;204</span> offres collectées en 30 jours");
  });

  it("le nombre d'offres au-dessus de 4 correspond aux tranches", () => {
    const high = SCORE_BINS.filter((_, i) => SCORE_FROM + i * SCORE_STEP >= 4);
    expect(total(high)).toBe(14);
    expect(html).toContain("14</span> offres au-dessus de 4 sur 5");
  });
});

describe("linePath", () => {
  it("place le maximum en haut et occupe toute la largeur", () => {
    expect(linePath([0, 5, 10], 100, 50)).toBe("M0.0 50.0 L50.0 25.0 L100.0 0.0");
  });
});

describe("storyProgress", () => {
  const steps = (tops: number[]) => tops.map((top) => ({ top, height: 500 }));

  it("vaut 0 tant qu'aucune étape n'a atteint la ligne de lecture", () => {
    expect(storyProgress(steps([900, 1400, 1900, 2400]), 1000)).toBe(0);
    expect(activeStep(0, 4)).toBe(-1);
  });

  it("compte les étapes franchies et la fraction de l'étape en cours", () => {
    // Ligne de lecture à 800 px, étape franchie sur 175 px : la 1re est passée, la 2e à moitié.
    expect(storyProgress(steps([-500, 712.5, 900, 1400]), 1000)).toBe(1.5);
    expect(activeStep(1.5, 4)).toBe(1);
  });

  it("plafonne à la dernière étape", () => {
    expect(storyProgress(steps([-3000, -2500, -2000, -1500]), 1000)).toBe(4);
    expect(activeStep(4, 4)).toBe(3);
  });
});

describe("page", () => {
  it("ne charge aucune ressource externe ni traceur", () => {
    expect(html).not.toMatch(/fonts\.googleapis|googletagmanager|analytics|<iframe/i);
  });
});
