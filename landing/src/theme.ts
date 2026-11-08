// Thème de la page : choix mémorisé, sinon réglage du système, sinon clair.
// Le même calcul tourne déjà dans le <head> d'index.html (avant l'affichage, pour éviter un flash).
export type Theme = "light" | "dark";
export const THEME_KEY = "ereuna-theme";

export function initialTheme(stored: string | null, systemDark: boolean): Theme {
  if (stored === "light" || stored === "dark") return stored;
  return systemDark ? "dark" : "light";
}

export const currentTheme = (): Theme => (document.documentElement.dataset.theme === "dark" ? "dark" : "light");

export function setTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
  // Le stockage peut être refusé (navigation privée) : le thème s'applique quand même pour cette visite.
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* pas de mémorisation possible */
  }
}
