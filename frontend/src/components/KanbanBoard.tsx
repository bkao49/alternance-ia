import type { Application, Status } from "../api/types";
import { formatDate } from "../format";
import { MoveSelect } from "./common";

type Props = {
  applications: Application[];
  statuses: Status[];
  onOpen: (application: Application) => void;
  onMove: (application: Application, statusId: string) => void;
};

/** Une colonne par statut. Pas de glisser-déposer : le « Déplacer vers… » fonctionne au clavier. */
export function KanbanBoard({ applications, statuses, onOpen, onMove }: Props) {
  const columns = [...statuses].sort((a, b) => a.position - b.position);

  return (
    <div className="kanban" role="list" aria-label="Candidatures par statut">
      {columns.map((status) => {
        const cards = applications.filter((a) => a.status.id === status.id);
        const headingId = `column-${status.id}`;
        return (
          <section key={status.id} className="column" role="listitem" aria-labelledby={headingId}>
            <h3 id={headingId} className="column-title">
              <span className="dot" style={{ background: status.color }} aria-hidden="true" />
              {status.name}
              <span className="count" aria-label={`${cards.length} candidature${cards.length > 1 ? "s" : ""}`}>
                {cards.length}
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
          </section>
        );
      })}
    </div>
  );
}
