import { useEffect, useId, useState } from "react";

import { unwrap } from "../api/client";
import { useApi } from "../api/context";
import type { Application, ApplicationEvent, Status } from "../api/types";
import { formatDateTime } from "../format";
import { Dialog, MoveSelect, StatusBadge } from "./common";

type Props = {
  application: Application;
  statuses: Status[];
  announcement: string;
  problem: string | null;
  onMove: (statusId: string) => void;
  onConfirmSent: () => Promise<void>;
  onClose: () => void;
};

export function ApplicationDialog({ application, statuses, announcement, problem, onMove, onConfirmSent, onClose }: Props) {
  const api = useApi();
  const [events, setEvents] = useState<ApplicationEvent[] | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [checked, setChecked] = useState(false);
  const [sending, setSending] = useState(false);
  const checkboxId = useId();
  const isSent = application.status.system_key === "sent";

  useEffect(() => {
    let active = true;
    api
      .GET("/applications/{applicationId}/events", { params: { path: { applicationId: application.id } } })
      .then((result) => active && setEvents(unwrap(result).items))
      .catch(() => active && setEvents([]));
    return () => {
      active = false;
    };
  }, [api, application.id, application.status.id]);

  async function confirmSent() {
    setSending(true); // une seule requête, même en cas de double clic
    try {
      await onConfirmSent();
    } finally {
      setSending(false);
    }
  }

  return (
    <Dialog title={application.company ?? "Candidature"} onClose={onClose}>
      {/* Dans la fenêtre : une zone d'annonce située derrière une modale n'est pas lue. */}
      <p className="visually-hidden" role="status" aria-live="polite">
        {announcement}
      </p>
      <p className="muted">{application.title}</p>
      <p>
        <StatusBadge status={application.status} />
        {application.sent_at && <span className="muted"> · envoyée le {formatDateTime(application.sent_at)}</span>}
      </p>
      {problem && (
        <p role="alert" className="error">
          {problem}
        </p>
      )}

      <div className="actions">
        <MoveSelect application={application} statuses={statuses} onMove={onMove} label="Changer le statut" />
        {!isSent && !confirming && (
          <button type="button" onClick={() => setConfirming(true)}>
            J'ai envoyé cette candidature
          </button>
        )}
      </div>

      {confirming && !isSent && (
        <fieldset className="confirm">
          <legend>Confirmer l'envoi</legend>
          <p className="muted">
            L'application n'envoie jamais rien à votre place. Confirmez seulement si vous avez vous-même envoyé la candidature.
          </p>
          <div className="check">
            <input id={checkboxId} type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
            <label htmlFor={checkboxId}>Je confirme avoir envoyé moi-même cette candidature</label>
          </div>
          <div className="actions">
            <button type="button" className="primary" disabled={!checked || sending} onClick={() => void confirmSent()}>
              Marquer comme envoyée
            </button>
            <button type="button" onClick={() => setConfirming(false)}>
              Annuler
            </button>
          </div>
        </fieldset>
      )}

      <h3>Historique</h3>
      {events === null ? (
        <p className="muted">Chargement…</p>
      ) : events.length === 0 ? (
        <p className="muted">Aucun événement.</p>
      ) : (
        <ol className="history">
          {events.map((event) => (
            <li key={event.id}>
              <strong>{event.from_status ? `${event.from_status} → ${event.to_status}` : event.to_status}</strong>
              <span className="muted"> · {formatDateTime(event.occurred_at)}</span>
              {event.comment && <p className="muted">{event.comment}</p>}
            </li>
          ))}
        </ol>
      )}
    </Dialog>
  );
}
