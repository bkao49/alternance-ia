import { useState, type FormEvent } from "react";

import { Dialog } from "./common";

export type NewApplication = {
  company: string;
  title: string;
  notes?: string;
  initial_status: "detected" | "to_prepare";
};

/** Renvoie `null` en cas de succès, sinon le message d'erreur à montrer dans la fenêtre. */
type Props = { onCreate: (body: NewApplication) => Promise<string | null>; onClose: () => void };

export function NewApplicationDialog({ onCreate, onClose }: Props) {
  const [company, setCompany] = useState("");
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [initialStatus, setInitialStatus] = useState<NewApplication["initial_status"]>("to_prepare");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const failure = await onCreate({
      company: company.trim(),
      title: title.trim(),
      notes: notes.trim() || undefined,
      initial_status: initialStatus,
    });
    setBusy(false);
    if (failure === null) onClose();
    else setError(failure); // la fenêtre reste ouverte : la saisie n'est pas perdue
  }

  return (
    <Dialog title="Nouvelle candidature" onClose={onClose}>
      <form onSubmit={submit} className="form">
        <label>
          Entreprise
          <input required maxLength={200} value={company} onChange={(e) => setCompany(e.target.value)} />
        </label>
        <label>
          Poste
          <input required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label>
          Statut de départ
          <select value={initialStatus} onChange={(e) => setInitialStatus(e.target.value as NewApplication["initial_status"])}>
            <option value="to_prepare">À préparer</option>
            <option value="detected">Détectée</option>
          </select>
        </label>
        <label>
          Notes (facultatif)
          <textarea rows={3} maxLength={5000} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="actions">
          <button type="submit" className="primary" disabled={busy || !company.trim() || !title.trim()}>
            Ajouter
          </button>
        </div>
      </form>
    </Dialog>
  );
}
