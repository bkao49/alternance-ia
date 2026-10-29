const dateFormat = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short", year: "numeric" });
const dateTimeFormat = new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short" });

export const formatDate = (iso: string) => dateFormat.format(new Date(iso));
export const formatDateTime = (iso: string) => dateTimeFormat.format(new Date(iso));

/** Taux entre 0 et 1 ; `null` quand il n'y a encore aucune candidature envoyée. */
export const formatRate = (rate: number | null) => (rate === null ? "n/a" : `${Math.round(rate * 100)} %`);
