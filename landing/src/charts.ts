import { COLLECTED, SCORE_BINS, SCORE_FROM, SCORE_STEP } from "./data";

const W = 320;
const H = 140;

// Chemin d'une courbe qui occupe toute la largeur, valeur maximale en haut.
export function linePath(values: number[], width = W, height = H): string {
  const max = Math.max(...values);
  const dx = width / (values.length - 1);
  return values
    .map((v, i) => `${i ? "L" : "M"}${(i * dx).toFixed(1)} ${(height - (v / max) * height).toFixed(1)}`)
    .join(" ");
}

function collectedSvg(): string {
  const line = linePath(COLLECTED);
  return `<svg viewBox="0 -8 ${W} ${H + 30}" aria-hidden="true">
    <path class="area" d="${line} L${W} ${H} L0 ${H} Z"/>
    <line class="axis" x1="0" y1="${H}" x2="${W}" y2="${H}"/>
    <path class="line" d="${line}"/>
    <text class="tick" x="0" y="${H + 18}">il y a 30 j</text>
    <text class="tick" x="${W}" y="${H + 18}" text-anchor="end">aujourd'hui</text>
  </svg>`;
}

function scoresSvg(): string {
  const max = Math.max(...SCORE_BINS);
  const slot = W / SCORE_BINS.length;
  const bars = SCORE_BINS.map((n, i) => {
    const h = (n / max) * H;
    const hot = SCORE_FROM + i * SCORE_STEP >= 4 ? " hot" : "";
    return `<rect class="bar${hot}" x="${(i * slot + 3).toFixed(1)}" y="${(H - h).toFixed(1)}" width="${(slot - 6).toFixed(1)}" height="${h.toFixed(1)}" rx="3" style="transition-delay:${i * 60}ms"/>`;
  }).join("");
  const ticks = [1, 2, 3, 4, 5]
    .map((s) => `<text class="tick" x="${(((s - SCORE_FROM) / SCORE_STEP) * slot).toFixed(1)}" y="${H + 18}" text-anchor="middle">${s}</text>`)
    .join("");
  return `<svg viewBox="-8 -8 ${W + 16} ${H + 30}" aria-hidden="true">${bars}<line class="axis" x1="0" y1="${H}" x2="${W}" y2="${H}"/>${ticks}</svg>`;
}

// Les graphiques sont décoratifs pour un lecteur d'écran : la légende de chaque figure porte l'information.
export function renderCharts(root: ParentNode = document) {
  const charts: Record<string, () => string> = { collected: collectedSvg, scores: scoresSvg };
  root.querySelectorAll<HTMLElement>("[data-chart]").forEach((fig) => {
    const draw = charts[fig.dataset.chart ?? ""];
    if (!draw) return;
    fig.insertAdjacentHTML("afterbegin", draw());
    // Tracé progressif : la courbe se dessine quand la figure apparaît (voir .motion .chart .line).
    const path = fig.querySelector<SVGPathElement>(".line");
    if (path && typeof path.getTotalLength === "function") {
      const len = path.getTotalLength();
      path.style.strokeDasharray = `${len}`;
      path.style.strokeDashoffset = fig.classList.contains("is-in") ? "0" : `${len}`;
    }
  });
}

export function showChart(fig: Element) {
  const path = fig.querySelector<SVGPathElement>(".line");
  if (path) path.style.strokeDashoffset = "0";
}
