import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import type { Application, Status } from "../api/types";
import { formatScore } from "../format";

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

/** La couleur vient de l'API : on n'en injecte dans le style que si c'est bien un code hexadécimal. */
export const safeColor = (color: string) => (HEX_COLOR.test(color) ? color : "#64748b");

/** Pastille de couleur + texte : l'information ne repose jamais sur la couleur seule. */
export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className="badge">
      <span className="dot" style={{ background: safeColor(status.color) }} aria-hidden="true" />
      {status.name}
    </span>
  );
}

/** Note sur 5 avec une petite jauge ; sans score (offre non analysée ou saisie à la main), un tiret lu « pas de score ». */
export function Score({ value }: { value: number | undefined }) {
  if (value === undefined) {
    return (
      <span className="score muted">
        <span aria-hidden="true">–</span>
        <span className="visually-hidden">pas de score</span>
      </span>
    );
  }
  return (
    <span className="score num">
      {formatScore(value)}
      <span className="visually-hidden"> sur 5</span>
      <span className="score-track" aria-hidden="true">
        <i style={{ width: `${(value / 5) * 100}%` }} />
      </span>
    </span>
  );
}

/**
 * Choix d'un statut + bouton de validation : changer la sélection au clavier ne déplace rien tant
 * qu'on n'a pas validé. « Envoyée » n'apparaît jamais ici : ce statut ne s'obtient que par la
 * confirmation d'envoi.
 */
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
  const [target, setTarget] = useState("");
  const name = application.company ?? "la candidature";
  const options = statuses.filter((s) => s.system_key !== "sent" && s.id !== application.status.id);

  return (
    <span className="move-group">
      <select className="move" aria-label={label ?? `Déplacer ${name} vers…`} value={target} onChange={(e) => setTarget(e.target.value)}>
        <option value="">Déplacer vers…</option>
        {options.map((status) => (
          <option key={status.id} value={status.id}>
            {status.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        className="move-go"
        disabled={!target}
        aria-label={`Valider le déplacement de ${name}`}
        onClick={() => {
          onMove(target);
          setTarget("");
        }}
      >
        Déplacer
      </button>
    </span>
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
