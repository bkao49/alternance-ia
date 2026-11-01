import type { DashboardStats, Me } from "../api/types";

/**
 * Le profil n'a pas encore de prénom (décision attendue du PO) : on salue avec le début de l'adresse
 * e-mail, la seule valeur disponible aujourd'hui.
 */
export function displayName(user: Me): string {
  const first = user.email.split("@")[0]?.split(/[._+-]/)[0] ?? "";
  return first ? first.charAt(0).toLocaleUpperCase("fr-FR") + first.slice(1) : user.email;
}

const plural = (n: number, one: string, many: string) => (n > 1 ? many : one);

function summary({ counts }: DashboardStats): string {
  const relevant =
    counts.relevant === 0
      ? "Aucune offre pertinente pour l'instant."
      : `${counts.relevant} ${plural(counts.relevant, "offre pertinente", "offres pertinentes")} à regarder.`;
  const pending =
    counts.to_validate === 0
      ? "Aucune candidature n'attend votre validation."
      : counts.to_validate === 1
        ? "Une candidature attend votre validation."
        : `${counts.to_validate} candidatures attendent votre validation.`;
  return `${relevant} ${pending}`;
}

export function Greeting({ user, stats, onCreate }: { user: Me; stats?: DashboardStats; onCreate: () => void }) {
  return (
    <header className="hello">
      <div>
        <h1>Bonjour {displayName(user)}.</h1>
        {stats && <p className="lede">{summary(stats)}</p>}
      </div>
      <button type="button" className="primary" onClick={onCreate}>
        Nouvelle candidature
      </button>
    </header>
  );
}

/** Grand chiffre des offres pertinentes : ouvre l'écran des offres. */
export function RelevantOffers({ count }: { count: number }) {
  return (
    <a className="offers" href="#offres">
      <span className="offers-big num" aria-hidden="true">
        {count}
      </span>
      <div>
        <h2 id="offers-title" className="offers-label">
          <span className="visually-hidden">{count}</span> {plural(count, "offre pertinente", "offres pertinentes")}
        </h2>
        <p className="offers-go">Voir la liste</p>
      </div>
    </a>
  );
}
