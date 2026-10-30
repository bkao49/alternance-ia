import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { unwrap } from "../api/client";
import { useApi } from "../api/context";
import type { ProfileFact, ProfileFactInput } from "../api/types";
import { Dialog } from "./common";

type Kind = ProfileFact["kind"];

const KINDS: [Kind, string][] = [
  ["experience", "Expérience"],
  ["education", "Formation"],
  ["project", "Projet"],
  ["skill", "Compétence"],
  ["certification", "Certification"],
  ["language", "Langue"],
  ["other", "Autre"],
];
/** Nom accessible court : un fait peut faire 1 000 caractères. */
const short = (text: string) => (text.length > 60 ? `${text.slice(0, 57)}…` : text);
const kindLabel = (kind: Kind) => KINDS.find(([value]) => value === kind)?.[1] ?? kind;

/** Une technologie par ligne ou séparée par des virgules ; doublons et vides retirés. */
export const toTechnologies = (text: string) => [...new Set(text.split(/[\n,]/).map((t) => t.trim()).filter(Boolean))];

function FactDialog({
  fact,
  onSave,
  onClose,
}: {
  fact: ProfileFact | null;
  onSave: (body: ProfileFactInput) => Promise<string | null>;
  onClose: () => void;
}) {
  const [kind, setKind] = useState<Kind>(fact?.kind ?? "experience");
  const [text, setText] = useState(fact?.text ?? "");
  const [startDate, setStartDate] = useState(fact?.start_date ?? "");
  const [endDate, setEndDate] = useState(fact?.end_date ?? "");
  const [technologies, setTechnologies] = useState(fact?.technologies.join(", ") ?? "");
  const [source, setSource] = useState(fact?.source ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const datesInverted = Boolean(startDate && endDate && endDate < startDate);
  const techs = toTechnologies(technologies);
  const techsInvalid = techs.length > 30 || techs.some((t) => t.length > 60);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    const failure = await onSave({
      kind,
      text: text.trim(),
      start_date: startDate || null,
      end_date: endDate || null,
      technologies: techs,
      source: source.trim() || null,
    });
    setBusy(false);
    if (failure === null) onClose();
    else setError(failure); // la fenêtre reste ouverte : la saisie n'est pas perdue
  }

  return (
    <Dialog title={fact ? "Modifier le fait" : "Ajouter un fait"} onClose={onClose}>
      <form onSubmit={submit} className="form">
        <label>
          Type
          <select value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
            {KINDS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Le fait, en une phrase vérifiable
          <textarea required rows={3} maxLength={1000} value={text} onChange={(e) => setText(e.target.value)} />
        </label>
        <label>
          Début (facultatif)
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </label>
        <label>
          Fin (facultatif, vide si en cours)
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </label>
        {datesInverted && (
          <p role="alert" className="error">
            La fin doit être après le début.
          </p>
        )}
        <label>
          Technologies (séparées par des virgules, 30 au plus, 60 caractères chacune)
          <input value={technologies} onChange={(e) => setTechnologies(e.target.value)} />
        </label>
        {techsInvalid && (
          <p role="alert" className="error">
            Trop de technologies, ou une technologie trop longue.
          </p>
        )}
        <label>
          Source (facultatif)
          <input maxLength={120} value={source} onChange={(e) => setSource(e.target.value)} />
        </label>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="actions">
          <button type="submit" className="primary" disabled={busy || datesInverted || techsInvalid || !text.trim()}>
            Enregistrer
          </button>
        </div>
      </form>
    </Dialog>
  );
}

export function ProfilePage() {
  const api = useApi();
  const [facts, setFacts] = useState<ProfileFact[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [editing, setEditing] = useState<ProfileFact | "new" | null>(null);
  const [announcement, setAnnouncement] = useState("");

  const [busyId, setBusyId] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);

  /** Lève l'erreur : l'appelant décide de l'afficher. */
  const fetchFacts = useCallback(async () => unwrap(await api.GET("/profile/facts")), [api]);

  const load = useCallback(async () => {
    try {
      setFacts(await fetchFacts());
      setLoadFailed(false);
      setProblem(null);
    } catch (failure) {
      setLoadFailed(true);
      setProblem(failure instanceof Error ? failure.message : "Chargement impossible");
    }
  }, [fetchFacts]);

  useEffect(() => {
    let active = true;
    fetchFacts()
      .then((items) => active && setFacts(items))
      .catch((e: unknown) => {
        if (!active) return;
        setLoadFailed(true);
        setProblem(e instanceof Error ? e.message : "Chargement impossible");
      });
    return () => {
      active = false;
    };
  }, [fetchFacts]);

  /** Renvoie `null` si l'action a réussi, sinon le message d'erreur. */
  async function run(action: () => Promise<unknown>, message: string): Promise<string | null> {
    try {
      await action();
      try {
        setFacts(await fetchFacts());
      } catch {
        return "Enregistré, mais la liste n'a pas pu être rechargée. Rechargez la page.";
      }
      setProblem(null);
      setAnnouncement(""); // vider puis réécrire : deux actions identiques sont relues
      setTimeout(() => setAnnouncement(message), 50);
      return null;
    } catch (failure) {
      return failure instanceof Error ? failure.message : "Action impossible";
    }
  }

  const save = (body: ProfileFactInput) =>
    editing && editing !== "new"
      ? run(async () => unwrap(await api.PUT("/profile/facts/{factId}", { params: { path: { factId: editing.id } }, body })), "Fait modifié")
      : run(async () => unwrap(await api.POST("/profile/facts", { body })), "Fait ajouté");

  async function remove(fact: ProfileFact) {
    if (busyId) return;
    setBusyId(fact.id);
    const failure = await run(async () => {
      const result = await api.DELETE("/profile/facts/{factId}", { params: { path: { factId: fact.id } } });
      // 404 : déjà supprimé (double clic, autre onglet) ; la liste rechargée le montre.
      if (result.error !== undefined && result.response.status !== 404) unwrap(result);
    }, "Fait supprimé");
    setBusyId(null);
    if (failure) setProblem(failure);
    else heading.current?.focus(); // le bouton cliqué n'existe plus : le focus ne doit pas tomber sur <body>
  }

  return (
    <section id="profil" aria-labelledby="profile-title">
      <div className="toolbar">
        <h1 id="profile-title" ref={heading} tabIndex={-1}>
          Mon profil
        </h1>
        <button type="button" className="primary" disabled={facts === null} onClick={() => setEditing("new")}>
          Ajouter un fait
        </button>
      </div>
      <p className="muted">
        Des faits vérifiables, un par ligne. Un CV ou une lettre ne contiendra jamais autre chose que ces faits.
      </p>
      {problem && (
        <p role="alert" className="error">
          {problem}{" "}
          {loadFailed && (
            <button type="button" onClick={() => void load()}>
              Réessayer
            </button>
          )}
        </p>
      )}
      {facts === null && !problem && <p role="status">Chargement…</p>}
      {facts?.length === 0 && <p>Aucun fait pour l'instant. Ajoutez votre première expérience, formation ou compétence.</p>}
      {facts && facts.length > 0 && (
        <ul className="facts">
          {facts.map((fact) => (
            <li key={fact.id}>
              <span className="chip">{kindLabel(fact.kind)}</span> <span>{fact.text}</span>
              <span className="muted">
                {(fact.start_date || fact.end_date) && ` · ${fact.start_date ?? "?"}${fact.end_date ? ` → ${fact.end_date}` : ""}`}
                {fact.technologies.length > 0 && ` · ${fact.technologies.join(", ")}`}
              </span>
              <span className="actions">
                <button type="button" disabled={busyId !== null} onClick={() => setEditing(fact)} aria-label={`Modifier : ${short(fact.text)}`}>
                  Modifier
                </button>
                <button type="button" disabled={busyId !== null} onClick={() => void remove(fact)} aria-label={`Supprimer : ${short(fact.text)}`}>
                  Supprimer
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="visually-hidden" role="status" aria-live="polite">
        {announcement}
      </p>
      {editing && <FactDialog fact={editing === "new" ? null : editing} onSave={save} onClose={() => setEditing(null)} />}
    </section>
  );
}
