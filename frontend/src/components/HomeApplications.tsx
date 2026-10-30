import type { Application } from "../api/types";
import type { ScoresByOffer } from "../hooks";
import { Score, StatusBadge } from "./common";

const HOME_ROWS = 5;

const scoreOf = (a: Application, scores: ScoresByOffer) => (a.offer_id ? scores[a.offer_id] : undefined);

/** Les mieux notées d'abord ; à score égal (ou sans score), les plus récentes. */
export function topApplications(applications: Application[], scores: ScoresByOffer): Application[] {
  return [...applications]
    .sort((a, b) => (scoreOf(b, scores) ?? -1) - (scoreOf(a, scores) ?? -1) || b.created_at.localeCompare(a.created_at))
    .slice(0, HOME_ROWS);
}

type Props = {
  applications: Application[];
  scores: ScoresByOffer;
  onOpen: (application: Application) => void;
  onSeeAll: () => void;
};

/** Liste courte de l'accueil : entreprise, poste, statut, score. Le détail et les filtres sont dans la vue complète. */
export function HomeApplications({ applications, scores, onOpen, onSeeAll }: Props) {
  const rows = topApplications(applications, scores);
  return (
    <section id="candidatures" aria-labelledby="home-applications-title">
      <div className="list-head">
        <h2 id="home-applications-title">Candidatures</h2>
        <button type="button" className="link accent-link" onClick={onSeeAll}>
          Tout voir
        </button>
      </div>
      {rows.length === 0 ? (
        <p className="empty">Aucune candidature pour l'instant.</p>
      ) : (
        <ul className="rows" aria-label="Candidatures les mieux notées">
          {rows.map((application) => (
            <li key={application.id}>
              <button type="button" className="row" onClick={() => onOpen(application)}>
                <span>
                  <b>{application.company}</b>
                  <span className="row-sub">{application.title}</span>
                </span>
                <StatusBadge status={application.status} />
                <Score value={scoreOf(application, scores)} />
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
