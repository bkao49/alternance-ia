import { useEffect, useState, type FormEvent } from "react";

import { unwrap } from "../api/client";
import { useApi } from "../api/context";

/** Pages carrières lues par le robot web : une adresse par ligne. Le serveur valide et dit quelle ligne pose problème. */
export function WebPagesEditor({ onSaved }: { onSaved: () => void }) {
  const api = useApi();
  const [text, setText] = useState<string | null>(null);
  const [max, setMax] = useState(10);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    api
      .GET("/sources/web/pages")
      .then(unwrap)
      .then((pages) => {
        if (!active) return;
        setText(pages.urls.join("\n"));
        setMax(pages.max);
      })
      .catch((e: unknown) => active && setError(e instanceof Error ? e.message : "Chargement impossible"));
    return () => {
      active = false;
    };
  }, [api]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    const urls = (text ?? "").split("\n").map((line) => line.trim()).filter(Boolean);
    try {
      setText(unwrap(await api.PUT("/sources/web/pages", { body: { urls } })).urls.join("\n"));
      setSaved(true);
      onSaved();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Enregistrement impossible");
    }
    setBusy(false);
  }

  if (text === null) return error ? <p role="alert" className="error">{error}</p> : <p role="status">Chargement…</p>;
  return (
    <form onSubmit={submit} className="form web-pages" aria-busy={busy}>
      <label>
        Pages à lire (une adresse par ligne, {max} au plus)
        <textarea
          rows={4}
          value={text}
          placeholder="https://carrieres.entreprise.fr/offres"
          onChange={(e) => {
            setText(e.target.value);
            setSaved(false);
          }}
        />
      </label>
      <p className="hint">
        Collez l'adresse d'une page d'offre ou d'une liste d'offres d'une entreprise. Le robot s'annonce, respecte le fichier
        robots.txt du site, attend entre deux visites et s'arrête dès que le site le bloque. Vérifiez que les conditions du site
        autorisent la lecture automatique. LinkedIn, Indeed et les sites qui exigent une connexion ne sont pas acceptés : pour
        eux, utilisez une alerte e-mail.
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <div className="actions">
        <button type="submit" disabled={busy}>
          Enregistrer les pages
        </button>
      </div>
      <p role="status" aria-live="polite">{saved ? "Pages enregistrées." : ""}</p>
    </form>
  );
}
