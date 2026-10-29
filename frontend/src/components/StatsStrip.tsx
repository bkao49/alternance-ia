import type { DashboardStats } from "../api/types";
import { formatRate } from "../format";

const COUNTERS: [keyof DashboardStats["counts"], string][] = [
  ["detected", "Détectées"],
  ["analyzed", "Analysées"],
  ["relevant", "Pertinentes"],
  ["prepared", "Préparées"],
  ["to_validate", "À valider"],
  ["sent", "Envoyées"],
  ["replies", "Réponses"],
  ["interviews", "Entretiens"],
  ["rejections", "Refus"],
  ["offers", "Offres reçues"],
];

const RATES: [keyof DashboardStats["conversion"], string][] = [
  ["sent_to_reply", "Envoyée → réponse"],
  ["sent_to_interview", "Envoyée → entretien"],
  ["sent_to_offer", "Envoyée → offre"],
];

export function StatsStrip({ stats }: { stats: DashboardStats }) {
  return (
    <section aria-labelledby="stats-title" className="stats">
      <h2 id="stats-title" className="visually-hidden">
        Chiffres clés
      </h2>
      <dl className="counters">
        {COUNTERS.map(([key, label]) => (
          <div key={key} className="counter">
            <dt>{label}</dt>
            <dd>{stats.counts[key]}</dd>
          </div>
        ))}
      </dl>
      <dl className="rates">
        {RATES.map(([key, label]) => (
          <div key={key} className="rate">
            <dt>{label}</dt>
            <dd>{formatRate(stats.conversion[key])}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
