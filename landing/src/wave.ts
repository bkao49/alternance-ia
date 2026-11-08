// Vague de particules Ereuna : une nappe de points qui ondule lentement, vue en perspective, dessinée en 2D
// (aucune bibliothèque, aucun fichier). Les crêtes s'éclairent, quelques points rouges « cherchent ».
// Le défilement pousse la vague, chaque section soulève une nouvelle houle, et les points rouges deviennent plus
// nombreux au fil du récit. Mouvement réduit : une seule image fixe. Onglet caché : le navigateur met en pause.

type Options = {
  scroll?: () => { p: number; s: number }; // avancement de la page (0 à 1) et défilement en px
  swells?: number; // nombre de houles sur la hauteur de la page
  ink?: () => string; // couleur des points, « r, g, b »
};

// Hauteur de la nappe : trois houles lentes qui se croisent.
export const waveHeight = (x: number, z: number, t: number) =>
  Math.sin(x * 2.1 + t * 0.55) * 0.55 +
  Math.sin(x * 4.3 - z * 2.2 + t * 0.35) * 0.28 +
  Math.cos(z * 3.1 + x * 1.2 - t * 0.45) * 0.32;

// Un point sur `every` est rouge : 1 sur 97 en haut de page, jusqu'à 1 sur 23 en bas.
export const redEvery = (p: number) => Math.max(23, Math.round(97 - p * 74));

export function startWave(canvas: HTMLCanvasElement, { scroll, swells = 6, ink = () => "236, 238, 244" }: Options = {}) {
  const g = canvas.getContext("2d");
  if (!g) return { stop: () => {}, redraw: () => {} };
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
  let w = 0;
  let h = 0;
  let cols = 0;
  let rows = 0;
  let frame = 0;

  function draw(time: number) {
    if (!g) return;
    g.clearRect(0, 0, w, h);
    const { p, s } = scroll ? scroll() : { p: 0, s: 0 };
    const t = time + s * 0.0022;
    const amp = 1 + 0.38 * Math.sin(p * Math.PI * swells);
    const every = redEvery(p);
    const dot = ink();
    // Sur écran haut et étroit (téléphone), la vague déborde des côtés au lieu de rapetisser.
    const fov = Math.min(Math.max(w, h * 0.7), h * 1.6) * 0.9;
    const cx = w / 2;
    const cy = h * (w < 700 ? 0.18 : 0.34); // téléphone : la vague au-dessus du titre
    for (let j = 0; j < rows; j++) {
      const z = j / (rows - 1); // 0 = loin, 1 = près
      const depth = 2.4 - z * 1.6;
      for (let i = 0; i < cols; i++) {
        const x = (i / (cols - 1)) * 2 - 1;
        const y = waveHeight(x * 1.6, z * 1.4, t) * amp;
        const sx = cx + ((x * 3.4) / depth) * fov * 0.5;
        const sy = cy + ((0.3 - y * 0.6) / depth) * fov * 0.5;
        if (sx < -4 || sx > w + 4 || sy < -4 || sy > h + 4) continue;
        // Plus la crête est haute et proche, plus le point est marqué et gros.
        const light = Math.max(0, Math.min(1, (y + 0.8) / 1.5)) * (0.4 + z * 0.6);
        if (light < 0.04) continue;
        const r = (0.8 + z * 1.5) * (0.55 + light * 0.75);
        const red = (i * 31 + j * 17) % every === 0 && light > 0.35;
        g.fillStyle = red ? `rgba(255, 90, 82, ${0.55 + light * 0.45})` : `rgba(${dot}, ${Math.min(1, light * 1.05)})`;
        g.fillRect(sx - r / 2, sy - r / 2, r, r);
      }
    }
  }

  function resize() {
    if (!g) return;
    const dpr = Math.min(devicePixelRatio || 1, 2);
    w = canvas.clientWidth;
    h = canvas.clientHeight;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    // Moins de points sur petit écran : la vague reste fluide sur téléphone.
    const dense = w > 900 ? 1 : 0.6;
    cols = Math.round(170 * dense);
    rows = Math.round(64 * dense);
    if (still) draw(4);
  }

  const t0 = performance.now();
  const tick = (now: number) => {
    draw((now - t0) / 1000);
    frame = requestAnimationFrame(tick);
  };

  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();
  if (!still) frame = requestAnimationFrame(tick);
  return {
    stop: () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
    },
    // Image fixe (mouvement réduit) : à redessiner quand le thème change.
    redraw: () => {
      if (still) draw(4);
    },
  };
}
