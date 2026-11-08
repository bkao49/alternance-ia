import "./styles.css";
import { currentTheme, setTheme } from "./theme";
import { startWave } from "./wave";

const root = document.documentElement;
root.classList.add("js");
const still = matchMedia("(prefers-reduced-motion: reduce)").matches;

// Vague : poussée par le défilement, une houle par section, plus discrète une fois l'accroche passée.
const canvas = document.querySelector<HTMLCanvasElement>(".wave");
const sections = document.querySelectorAll("main > section, main > div").length;
const page = () => {
  const max = root.scrollHeight - innerHeight;
  return { p: max > 0 ? scrollY / max : 0, s: scrollY };
};
const wave = canvas
  ? startWave(canvas, { scroll: page, swells: sections, ink: () => (currentTheme() === "dark" ? "236, 238, 244" : "29, 29, 31") })
  : null;

// Bouton clair / sombre, choix mémorisé.
const themeBtn = document.querySelector<HTMLButtonElement>(".theme");
function showTheme() {
  if (!themeBtn) return;
  const dark = currentTheme() === "dark";
  themeBtn.textContent = dark ? "Mode clair" : "Mode sombre";
  themeBtn.setAttribute("aria-pressed", String(dark));
}
themeBtn?.addEventListener("click", () => {
  setTheme(currentTheme() === "dark" ? "light" : "dark");
  showTheme();
  wave?.redraw();
});
showTheme();

// Chaque étape « déferle » : --p va de 0 (sous l'écran) à 1 (bien en vue).
const scenes = [...document.querySelectorAll<HTMLElement>(".scene")];
function update() {
  if (canvas) canvas.style.opacity = String(1 - Math.min(0.6, (scrollY / innerHeight) * 0.6));
  if (still) return;
  const vh = innerHeight;
  for (const el of scenes) {
    const p = Math.min(1, Math.max(0, (vh - el.getBoundingClientRect().top) / (vh * 0.7)));
    el.style.setProperty("--p", p.toFixed(3));
  }
}
addEventListener("scroll", update, { passive: true });
addEventListener("resize", update);
update();

// Blocs simples : apparition une fois visibles (tout est affiché sans IntersectionObserver).
const revealables = document.querySelectorAll(".reveal");
if ("IntersectionObserver" in window) {
  const io = new IntersectionObserver(
    (entries) => entries.filter((e) => e.isIntersecting).forEach((e) => { e.target.classList.add("is-in"); io.unobserve(e.target); }),
    { threshold: 0.15 },
  );
  revealables.forEach((el) => io.observe(el));
} else {
  revealables.forEach((el) => el.classList.add("is-in"));
}

// Menu sur téléphone : on le ferme avant de descendre à la section (il bloque le défilement).
const burger = document.querySelector<HTMLButtonElement>(".burger");
function setOpen(open: boolean) {
  document.body.classList.toggle("open", open);
  burger?.setAttribute("aria-expanded", String(open));
  burger?.setAttribute("aria-label", open ? "Fermer le menu" : "Ouvrir le menu");
}
burger?.addEventListener("click", () => setOpen(!document.body.classList.contains("open")));
document.querySelectorAll<HTMLAnchorElement>(".links a").forEach((a) =>
  a.addEventListener("click", (e) => {
    setOpen(false);
    const href = a.getAttribute("href") ?? "";
    const target = href.startsWith("#") ? document.querySelector(href) : null;
    if (!target) return;
    e.preventDefault();
    target.scrollIntoView({ behavior: still ? "auto" : "smooth" });
    history.replaceState(null, "", href);
  }),
);
addEventListener("keydown", (e) => { if (e.key === "Escape") setOpen(false); });
