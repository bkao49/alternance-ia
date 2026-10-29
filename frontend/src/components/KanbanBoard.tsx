import type { Application, Status } from "../api/types";
import { formatDate } from "../format";
import { MoveSelect, safeColor } from "./common";

type Props = {
  applications: Application[];
  statuses: Status[];
  onOpen: (application: Application) => void;
  onMove: (application: Application, statusId: string) => void;
};

/** Une colonne par statut. Pas de glisser-déposer : le menu « Déplacer vers… » fonctionne au clavier. */
export function KanbanBoard({ applications, statuses, onOpen, onMove }: Props) {
  const columns = [...statuses].sort((a, b) => a.position - b.position);

  return (
    <ul className="kanban" aria-label="Candidatures par statut">
      {columns.map((status) => {
        const cards = applications.filter((a) => a.status.id === status.id);
        const headingId = `column-${status.id}`;
        return (
          <li key={status.id} className="column" aria-labelledby={headingId}>
            <h3 id={headingId} className="column-title">
              <span className="dot" style={{ background: safeColor(status.color) }} aria-hidden="true" />
              {status.name}
              <span className="count">
                <span aria-hidden="true">{cards.length}</span>
                <span className="visually-hidden">
                  {" "}
                  : {cards.length} candidature{cards.length > 1 ? "s" : ""}
                </span>
              </span>
            </h3>
            {status.system_key === "sent" && (
              <p className="hint">On y arrive en confirmant l'envoi depuis la fiche de la candidature.</p>
            )}
            <ul className="cards">
              {cards.map((application) => (
                <li key={application.id} className="card-item">
                  <button type="button" className="card-title" onClick={() => onOpen(application)}>
                    {application.company}
                  </button>
                  <p className="card-sub">{application.title}</p>
                  <p className="card-date">{formatDate(application.created_at)}</p>
                  <MoveSelect
                    application={application}
                    statuses={statuses}
                    onMove={(statusId) => onMove(application, statusId)}
                  />
                </li>
              ))}
            </ul>
          </li>
        );
      })}
    </ul>
  );
}
