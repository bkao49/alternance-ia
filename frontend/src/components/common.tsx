import { useEffect, useId, useRef, type ReactNode } from "react";

import type { Application, Status } from "../api/types";

/** Pastille de couleur + texte : l'information ne repose jamais sur la couleur seule. */
export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className="badge">
      <span className="dot" style={{ background: status.color }} aria-hidden="true" />
      {status.name}
    </span>
  );
}

/** « Envoyée » n'apparaît jamais ici : ce statut ne s'obtient que par la confirmation d'envoi. */
export function MoveSelect({
  application,
  statuses,
  onMove,
  label,
}: {
  application: Application;
  statuses: Status[];
  onMove: (statusId: string) => void;
  label?: string;
}) {
  const options = statuses.filter((s) => s.system_key !== "sent" && s.id !== application.status.id);
  return (
    <select
      className="move"
      aria-label={label ?? `Déplacer ${application.company ?? "la candidature"} vers…`}
      value=""
      onChange={(event) => event.target.value && onMove(event.target.value)}
    >
      <option value="">Déplacer vers…</option>
      {options.map((status) => (
        <option key={status.id} value={status.id}>
          {status.name}
        </option>
      ))}
    </select>
  );
}

/** Fenêtre modale native : focus piégé, fermeture par Échap, rendu accessible. */
export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);

  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(event) => event.target === ref.current && ref.current?.close()}
    >
      <div className="dialog-body">
        <header className="dialog-header">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="icon" aria-label="Fermer" onClick={() => ref.current?.close()}>
            ×
          </button>
        </header>
        {children}
      </div>
    </dialog>
  );
}
