// Avancement du récit, de 0 (accroche) à 4 (dernière étape lue) : chaque étape compte pour 1 quand elle a
// entièrement franchi la ligne de lecture, placée aux quatre cinquièmes de la fenêtre.
// Elle est franchie sur 35 % de la hauteur de l'étape, pour que le dernier état soit atteint avant la fin du récit.
export function storyProgress(steps: { top: number; height: number }[], viewport: number): number {
  const line = viewport * 0.8;
  return steps.reduce((sum, s) => sum + clamp01((line - s.top) / (s.height * 0.35)), 0);
}

export function activeStep(progress: number, count: number): number {
  return progress <= 0 ? -1 : Math.min(Math.floor(progress), count - 1);
}

export const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
export const smooth = (t: number) => t * t * (3 - 2 * t);
