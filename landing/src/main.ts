import "./styles.css";
import { renderCharts, showChart } from "./charts";
import { activeStep, storyProgress } from "./story";

const motion = document.documentElement.classList.contains("motion");
const steps = [...document.querySelectorAll<HTMLElement>("[data-step]")];

renderCharts();

// Révélations douces : une fois visible, un bloc le reste.
const reveal = (el: Element) => {
  el.classList.add("is-in");
  if (el.matches("[data-chart]")) showChart(el);
};
const revealables = document.querySelectorAll("[data-reveal]");
if (motion && "IntersectionObserver" in window) {
  const io = new IntersectionObserver(
    (entries) => entries.filter((e) => e.isIntersecting).forEach((e) => { reveal(e.target); io.unobserve(e.target); }),
    { threshold: 0.2 },
  );
  revealables.forEach((el) => io.observe(el));
} else {
  revealables.forEach(reveal);
}

let progress = 0;
function onScroll() {
  progress = storyProgress(steps.map((s) => s.getBoundingClientRect()), window.innerHeight);
  const active = activeStep(progress, steps.length);
  steps.forEach((s, i) => s.classList.toggle("is-active", i === active));
}
addEventListener("scroll", onScroll, { passive: true });
addEventListener("resize", onScroll);
onScroll();

function hasWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") ?? c.getContext("webgl"));
  } catch {
    return false;
  }
}

// La 3D (three.js) n'est chargée que si elle sera montrée ; sinon la version 2D reste affichée.
const canvas = document.querySelector<HTMLCanvasElement>("#scene");
if (canvas && motion && hasWebGL()) {
  import("./scene")
    .then(async ({ startScene }) => {
      await startScene(canvas, () => progress);
      canvas.parentElement?.classList.add("has-3d");
    })
    .catch(() => canvas.parentElement?.classList.remove("has-3d"));
}
