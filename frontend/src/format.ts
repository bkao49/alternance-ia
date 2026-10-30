const dateFormat = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", year: "numeric" });
const dateTimeFormat = new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" });

export const formatDate = (iso: string) => dateFormat.format(new Date(iso));
/** Score sur 5 avec une virgule (« 4,4 ») ; tiret quand l'offre n'a pas été analysée. */
export const formatScore = (score: number | undefined) => (score === undefined ? "–" : score.toFixed(1).replace(".", ","));

export const formatDateTime = (iso: string) => dateTimeFormat.format(new Date(iso));
