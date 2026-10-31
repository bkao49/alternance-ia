import { useCallback, useEffect, useRef, useState, type DragEvent, type KeyboardEvent } from "react";

import { ApiFailure, unwrap } from "../api/client";
import { useApi } from "../api/context";
import type { ProfileCv } from "../api/types";
import { Dialog } from "./common";

const MAX_BYTES = 5 * 1024 * 1024;
const POLL_MS = 1500;

const FAILURES: Record<NonNullable<ProfileCv["error_code"]>, string> = {
  encrypted: "Ce PDF est protégé par un mot de passe. Enregistrez-en une version sans protection.",
  too_many_pages: "Ce document a trop de pages (30 au plus).",
  no_text: "Aucun texte lisible dans ce fichier. S'il s'agit d'un scan, exportez un PDF avec du texte.",
  timeout: "La lecture a pris trop de temps. Réessayez avec un fichier plus léger.",
  unreadable: "Ce fichier est illisible ou abîmé.",
};

/** Contrôle avant envoi, pour répondre vite ; le serveur refait toutes les vérifications. */
export function checkCvFile(file: { name: string; size: number }): string | null {
  if (!/\.(pdf|docx)$/i.test(file.name)) return "Seuls les fichiers PDF et DOCX sont acceptés.";
  if (file.size > MAX_BYTES) return "Ce fichier dépasse 5 Mo.";
  if (file.size === 0) return "Ce fichier est vide.";
  return null;
}

export function CvImport({ onFactsChanged }: { onFactsChanged: () => void }) {
  const api = useApi();
  const [cv, setCv] = useState<ProfileCv | null | undefined>(undefined); // undefined : chargement, null : aucun CV
  const [problem, setProblem] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const wasProcessing = useRef(false);

  const refresh = useCallback(async () => {
    const result = await api.GET("/profile/cv");
    if (result.response.status === 404) return null;
    return unwrap(result);
  }, [api]);

  useEffect(() => {
    let active = true;
    refresh()
      .then((value) => active && setCv(value))
      .catch((e: unknown) => active && (setCv(null), setProblem(e instanceof Error ? e.message : "Chargement impossible")));
    return () => {
      active = false;
    };
  }, [refresh]);

  // Tant que le serveur lit le CV, on demande régulièrement où il en est.
  const processing = cv?.status === "processing";
  useEffect(() => {
    if (!processing) {
      if (wasProcessing.current && cv?.status === "done") {
        setAnnouncement(`${cv.facts_proposed} fait(s) proposé(s) à relire.`);
        onFactsChanged();
      }
      wasProcessing.current = false;
      return;
    }
    wasProcessing.current = true;
    const timer = setInterval(() => {
      refresh().then(setCv, () => undefined);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [processing, cv, refresh, onFactsChanged]);

  async function send(file: File) {
    const refused = checkCvFile(file);
    if (refused) return setProblem(refused);
    setProblem(null);
    setUploading(true);
    try {
      const result = await api.POST("/profile/cv", {
        body: { file: file as unknown as string },
        bodySerializer: () => {
          const form = new FormData();
          form.append("file", file);
          return form;
        },
      });
      setCv(unwrap(result));
      onFactsChanged(); // l'ancien CV a pu retirer ses faits à relire
    } catch (failure) {
      setProblem(failure instanceof Error ? failure.message : "Dépôt impossible");
    }
    setUploading(false);
    if (input.current) input.current.value = "";
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file && !uploading) void send(file);
  }

  const onKey = (event: KeyboardEvent) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      input.current?.click();
    }
  };

  async function remove() {
    try {
      const result = await api.DELETE("/profile/cv");
      if (result.error !== undefined && result.response.status !== 404) unwrap(result);
      setCv(null);
      setProblem(null);
      setAnnouncement("CV et faits supprimés.");
      onFactsChanged();
    } catch (failure) {
      setProblem(failure instanceof ApiFailure || failure instanceof Error ? failure.message : "Suppression impossible");
    }
    setConfirming(false);
  }

  async function download() {
    try {
      const link = unwrap(await api.POST("/profile/cv/download-link"));
      window.location.assign(`/api${link.url}`); // lien signé de 60 s, pièce jointe
    } catch (failure) {
      setProblem(failure instanceof Error ? failure.message : "Téléchargement impossible");
    }
  }

  return (
    <section aria-labelledby="cv-title" className="cv-import">
      <h2 id="cv-title">Mon CV</h2>
      <p className="muted">
        Déposez votre CV (PDF ou DOCX, 5 Mo au plus). L'application en tire des faits à relire : rien n'est utilisé tant
        que vous ne l'avez pas validé. Le texte du CV reste sur cette application.
      </p>
      <div
        className={`dropzone${dragging ? " is-dragging" : ""}`}
        role="button"
        tabIndex={0}
        aria-label="Déposer un CV : cliquer ou glisser un fichier PDF ou DOCX"
        aria-disabled={uploading || processing}
        onClick={() => !uploading && !processing && input.current?.click()}
        onKeyDown={onKey}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        {uploading ? "Envoi en cours…" : "Glissez votre CV ici ou appuyez sur Entrée pour choisir un fichier"}
        <input
          ref={input}
          type="file"
          hidden
          accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
          data-testid="cv-file"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void send(file);
          }}
        />
      </div>
      {problem && (
        <p role="alert" className="error">
          {problem}
        </p>
      )}
      {cv === undefined && <p role="status">Chargement…</p>}
      {cv === null && !problem && <p className="muted">Aucun CV déposé.</p>}
      {cv && (
        <div className="cv-state">
          <p>
            <strong>{cv.original_name}</strong> <span className="chip">{cv.file_type.toUpperCase()}</span>
          </p>
          {cv.status === "processing" && (
            <p role="progressbar" aria-label="Lecture du CV en cours" aria-busy="true" className="muted">
              Lecture du CV en cours…
            </p>
          )}
          {cv.status === "done" && (
            <p>{cv.facts_proposed > 0 ? `${cv.facts_proposed} fait(s) proposé(s) à relire ci-dessous.` : "Aucun fait nouveau trouvé."}</p>
          )}
          {cv.status === "failed" && (
            <p role="alert" className="error">
              {FAILURES[cv.error_code ?? "unreadable"]}
            </p>
          )}
          <div className="actions">
            <button type="button" onClick={() => void download()}>
              Télécharger mon CV
            </button>
            <button type="button" onClick={() => setConfirming(true)}>
              Supprimer mon CV et mes faits
            </button>
          </div>
        </div>
      )}
      <p className="visually-hidden" role="status" aria-live="polite">
        {announcement}
      </p>
      {confirming && (
        <Dialog title="Supprimer mon CV et mes faits ?" onClose={() => setConfirming(false)}>
          <p>
            Le fichier et tous les faits qui en viennent (validés ou non) seront supprimés. Les faits que vous avez saisis
            vous-même restent. Cette action est définitive.
          </p>
          <div className="actions">
            <button type="button" onClick={() => setConfirming(false)}>
              Annuler
            </button>
            <button type="button" className="primary" onClick={() => void remove()}>
              Supprimer définitivement
            </button>
          </div>
        </Dialog>
      )}
    </section>
  );
}
