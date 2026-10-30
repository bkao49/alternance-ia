// Scène 3D unique : des cartes d'offres tombent, se rangent par score, puis la meilleure est validée.
// Un état par moment du récit (0 accroche, 1 collecte, 2 score, 3 CV, 4 validation) ; la scène interpole
// entre deux états selon l'avancement du défilement.
import {
  BufferGeometry,
  CanvasTexture,
  Color,
  Group,
  Line,
  LineBasicMaterial,
  LineLoop,
  Mesh,
  MeshBasicMaterial,
  PerspectiveCamera,
  PlaneGeometry,
  Scene,
  SRGBColorSpace,
  Shape,
  ShapeGeometry,
  Vector3,
  WebGLRenderer,
} from "three";
import { clamp01, smooth } from "./story";

const CARD_W = 3.2;
const CARD_H = 0.62;
const GAP = 0.74;
const BG = new Color("#0d0d0f");
const SURFACE = new Color("#141416");
const BORDER = new Color("#3a3a41");
const ACCENT = new Color("#d6231e");
const ACCENT_TEXT = new Color("#ff5a52");
const WHITE = new Color("#ffffff");

type State = { pos: [number, number, number]; rot: [number, number, number]; scale: number; alpha: number; bar: number; red: number };

// Générateur pseudo-aléatoire déterministe : la même scène à chaque visite.
function random(seed: number) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Offres fictives affichées sur les cartes : [poste, entreprise, contrat, score sur 5].
export const OFFERS: [string, string, string, number][] = [
  ["Data Engineer", "Initech Data", "Alternance", 4.4],
  ["Machine Learning Engineer", "Globex IA", "CDI", 4.6],
  ["Data Analyst", "Umbrella Data", "Stage", 4.2],
  ["MLOps Engineer", "Stark Mobilité", "CDD", 4.1],
  ["Ingénieur IA générative", "Hooli Labs", "CDI", 3.9],
  ["Data Scientist", "Wayne Santé", "Alternance", 3.7],
  ["Analytics Engineer", "Soylent Retail", "CDI", 3.4],
  ["BI Developer", "Vandelay Conseil", "Stage", 3.1],
  ["Développeur Python", "Cyberdyne", "CDD", 2.8],
  ["Chargé d'études", "Tyrell Assurances", "CDI", 2.4],
  ["Technicien support", "Massive Dynamic", "CDD", 1.9],
  ["Assistant marketing", "Pied Piper", "Stage", 1.5],
];

export function cardStates(): State[][] {
  const rnd = random(7);
  const scores = OFFERS.map((o) => o[3]);
  const rank = scores.map((s) => scores.filter((o) => o > s).length);
  return scores.map((score, i) => {
    const r = rank[i] ?? 0;
    const dim = score < 3.5 ? 0.35 : 1;
    const top = 4.1 - r * GAP;
    const cloud: State = {
      pos: [(rnd() - 0.5) * 7, -1.5 + rnd() * 6.5, -5 + rnd() * 6],
      rot: [(rnd() - 0.5) * 1.2, (rnd() - 0.5) * 1.2, (rnd() - 0.5) * 0.8],
      scale: 1, alpha: 0.9, bar: 0, red: 0,
    };
    const fallen: State = { pos: [(rnd() - 0.5) * 0.5, 4.1 - i * GAP, 0], rot: [0, 0, (rnd() - 0.5) * 0.12], scale: 1, alpha: 1, bar: 0, red: 0 };
    const sorted: State = { pos: [0, top, 0], rot: [0, 0, 0], scale: 1, alpha: dim, bar: score / 5, red: 0 };
    const shortlist: State = r < 3
      ? { pos: [0, 1.1 - r * 1.1, 0.8], rot: [0, 0, 0], scale: 1.1, alpha: 1, bar: score / 5, red: 0 }
      : { pos: [0, top, -3], rot: [0, 0, 0], scale: 1, alpha: 0.12, bar: score / 5, red: 0 };
    const chosen: State = r === 0
      ? { pos: [0, 0.4, 1.2], rot: [0, 0, 0], scale: 1.3, alpha: 1, bar: score / 5, red: 1 }
      : r < 3
        ? { pos: [0, -1.4 - r * 0.8, 0.5], rot: [0, 0, 0], scale: 1.1, alpha: 0.4, bar: score / 5, red: 0 }
        : { ...shortlist, alpha: 0 };
    return [cloud, fallen, sorted, shortlist, chosen];
  });
}

function roundedRect(w: number, h: number, r: number) {
  const s = new Shape();
  s.moveTo(-w / 2 + r, -h / 2);
  s.lineTo(w / 2 - r, -h / 2);
  s.quadraticCurveTo(w / 2, -h / 2, w / 2, -h / 2 + r);
  s.lineTo(w / 2, h / 2 - r);
  s.quadraticCurveTo(w / 2, h / 2, w / 2 - r, h / 2);
  s.lineTo(-w / 2 + r, h / 2);
  s.quadraticCurveTo(-w / 2, h / 2, -w / 2, h / 2 - r);
  s.lineTo(-w / 2, -h / 2 + r);
  s.quadraticCurveTo(-w / 2, -h / 2, -w / 2 + r, -h / 2);
  return s;
}

const PX = 480; // pixels de texture par unité de scène
const LABEL_W = Math.round(CARD_W * PX);
const LABEL_H = Math.round(CARD_H * PX);

function drawLabel(offer: [string, string, string, number]): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = LABEL_W;
  c.height = LABEL_H;
  const g = c.getContext("2d")!;
  g.textBaseline = "alphabetic";
  g.fillStyle = "#f4f4f4";
  g.font = '500 44px Geist, system-ui, sans-serif';
  g.fillText(offer[0], 38, 112, LABEL_W - 330);
  g.font = '400 30px Geist, system-ui, sans-serif';
  g.fillStyle = "#d0d0d6";
  g.fillText(offer[1], 38, 160, 520);
  // Pastille du contrat, à droite du nom de l'entreprise.
  const x = 38 + Math.min(520, g.measureText(offer[1]).width) + 22;
  g.font = '400 24px Geist, system-ui, sans-serif';
  const w = g.measureText(offer[2]).width + 28;
  g.strokeStyle = "#a6a6ae";
  g.lineWidth = 2;
  g.beginPath();
  g.roundRect(x, 134, w, 34, 17);
  g.stroke();
  g.fillText(offer[2], x + 14, 159);
  return c;
}

function drawScore(score: number): HTMLCanvasElement {
  const c = document.createElement("canvas");
  c.width = 320;
  c.height = 200;
  const g = c.getContext("2d")!;
  g.fillStyle = "#ffffff";
  g.textAlign = "right";
  g.font = 'italic 400 128px "Instrument Serif", "Times New Roman", serif';
  g.fillText(score.toFixed(1).replace(".", ","), 300, 150);
  return c;
}

function texturePlane(source: HTMLCanvasElement, w: number, h: number) {
  const map = new CanvasTexture(source);
  map.colorSpace = SRGBColorSpace;
  map.anisotropy = 4;
  return new Mesh(new PlaneGeometry(w, h), new MeshBasicMaterial({ map, transparent: true, alphaTest: 0.04 }));
}

function buildCard(offer: [string, string, string, number], fillGeo: ShapeGeometry, edgeGeo: BufferGeometry, lineGeo: PlaneGeometry, checkGeo: BufferGeometry) {
  const mat = (color: Color) => new MeshBasicMaterial({ color: color.clone(), transparent: true });
  const fill = new Mesh(fillGeo, mat(SURFACE));
  const edge = new LineLoop(edgeGeo, new LineBasicMaterial({ color: BORDER.clone(), transparent: true }));
  const label = texturePlane(drawLabel(offer), CARD_W, CARD_H);
  label.position.z = 0.02;
  const score = texturePlane(drawScore(offer[3]), 0.67, 0.42);
  score.position.set(CARD_W / 2 - 0.62, 0.02, 0.03);
  const bar = new Mesh(lineGeo, mat(ACCENT_TEXT));
  const check = new Line(checkGeo, new LineBasicMaterial({ color: WHITE.clone(), transparent: true, opacity: 0 }));
  check.position.set(CARD_W / 2 - 0.32, -0.2, 0.04);
  const group = new Group();
  group.add(fill, edge, label, score, bar, check);
  return { group, fill, edge, label, score, bar, check };
}

function startNow(canvas: HTMLCanvasElement, progress: () => number): () => void {
  const renderer = new WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(BG);
  const scene = new Scene();
  const camera = new PerspectiveCamera(35, 1, 0.1, 100);
  camera.position.set(0, 0, 16);

  const shape = roundedRect(CARD_W, CARD_H, 0.14);
  const fillGeo = new ShapeGeometry(shape, 6);
  const edgeGeo = new BufferGeometry().setFromPoints(shape.getPoints(6));
  const lineGeo = new PlaneGeometry(1, 0.05);
  const checkGeo = new BufferGeometry().setFromPoints([new Vector3(-0.12, 0, 0), new Vector3(-0.03, -0.09, 0), new Vector3(0.14, 0.1, 0)]);

  const world = new Group();
  world.rotation.set(-0.28, 0.32, 0.04);
  scene.add(world);
  const states = cardStates();
  const cards = states.map((_, i) => buildCard(OFFERS[i]!, fillGeo, edgeGeo, lineGeo, checkGeo));
  cards.forEach((c) => world.add(c.group));

  const resize = () => {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    // Une fenêtre large et basse (mobile) rapproche la caméra pour garder des cartes lisibles.
    camera.position.z = camera.aspect > 1.4 ? 11 : 16;
    camera.updateProjectionMatrix();
  };
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);
  resize();

  const tmp = new Color();
  let shown = 0;
  let last = performance.now();
  let frame = 0;
  let visible = true;
  const io = new IntersectionObserver(([e]) => {
    visible = !!e?.isIntersecting;
    if (visible && !frame) frame = requestAnimationFrame(tick);
  });
  io.observe(canvas);

  function tick(now: number) {
    frame = 0;
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    shown += (progress() - shown) * (1 - Math.exp(-dt * 5));
    const k = Math.min(3, Math.floor(shown));
    const t = smooth(clamp01(shown - k));
    const drift = 1 - clamp01(shown);
    const time = now / 1000;

    states.forEach((s, i) => {
      const a = s[k]!;
      const b = s[k + 1]!;
      const c = cards[i]!;
      const g = c.group;
      const mix = (x: number, y: number) => x + (y - x) * t;
      g.position.set(
        mix(a.pos[0], b.pos[0]),
        mix(a.pos[1], b.pos[1]) + Math.sin(time * 0.6 + i) * 0.18 * drift,
        mix(a.pos[2], b.pos[2]),
      );
      g.rotation.set(
        mix(a.rot[0], b.rot[0]) + Math.sin(time * 0.4 + i * 2) * 0.08 * drift,
        mix(a.rot[1], b.rot[1]),
        mix(a.rot[2], b.rot[2]),
      );
      g.scale.setScalar(mix(a.scale, b.scale));
      const alpha = mix(a.alpha, b.alpha);
      const red = mix(a.red, b.red);
      // La barre de score court sous le texte ; le score s'affiche quand les offres sont notées.
      const bar = mix(a.bar, b.bar);
      const barW = Math.max(0.001, bar * 2.2);
      c.bar.scale.set(barW, 1, 1);
      c.bar.position.set(-CARD_W / 2 + 0.075 + barW / 2, -0.235, 0.01);
      (c.fill.material as MeshBasicMaterial).color.copy(tmp.copy(SURFACE).lerp(ACCENT, red));
      (c.fill.material as MeshBasicMaterial).opacity = alpha;
      c.edge.material.opacity = alpha * (1 - red);
      (c.label.material as MeshBasicMaterial).opacity = alpha;
      (c.score.material as MeshBasicMaterial).color.copy(tmp.copy(ACCENT_TEXT).lerp(WHITE, red));
      (c.score.material as MeshBasicMaterial).opacity = alpha * clamp01(bar * 8);
      (c.bar.material as MeshBasicMaterial).color.copy(tmp.copy(ACCENT_TEXT).lerp(WHITE, red));
      (c.bar.material as MeshBasicMaterial).opacity = alpha;
      c.check.material.opacity = red;
    });

    renderer.render(scene, camera);
    if (visible) frame = requestAnimationFrame(tick);
  }
  frame = requestAnimationFrame(tick);

  return () => {
    cancelAnimationFrame(frame);
    io.disconnect();
    ro.disconnect();
    renderer.dispose();
  };
}

// Les textures de texte sont dessinées avec les polices du site : on attend qu'elles soient chargées.
export async function startScene(canvas: HTMLCanvasElement, progress: () => number): Promise<() => void> {
  await Promise.all([
    document.fonts.load('500 44px "Geist"'),
    document.fonts.load('400 30px "Geist"'),
    document.fonts.load('italic 400 128px "Instrument Serif"'),
  ]).catch(() => undefined);
  return startNow(canvas, progress);
}
