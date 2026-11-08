import { useEffect, useState } from "react";

import { unwrap } from "../api/client";
import { useApi } from "../api/context";
import type { Source } from "../api/types";

const INTERVALS: [number, string][] = [
  [60, "Toutes les heures"],
  [120, "Toutes les 2 heures"],
  [360, "Toutes les 6 heures"],
  [720, "Deux fois par jour"],
  [1440, "Une fois par jour"],
];

const intervalLabel = (minutes: number) =>
  INTERVALS.find(([value]) => value === minutes)?.[1] ?? `Toutes les ${minutes} minutes`;

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : null;

function stateOf(source: Source): { label: string; note?: string } {
  if (source.blocked) return { label: "Bloquée", note: source.blocked_cause ?? undefined };
  if (!source.configured) return { label: "Clé manquante" };
  return { label: source.enabled ? "Activée" : "Désactivée" };
}

function SourceCard({ source, onSave }: { source: Source; onSave: (body: SaveBody) => Promise<string | null> }) {
  const [problem, setProblem] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const state = stateOf(source);
  const effective = source.interval_minutes ?? source.default_interval_minutes;
  const options = INTERVALS.some(([value]) => value === effective) ? INTERVALS : [...INTERVALS, [effective, intervalLabel(effective)] as [number, string]];

  async function save(body: SaveBody) {
    setBusy(true);
    setProblem(await onSave(body));
    setConfirming(false);
    setBusy(false);
  }
  const keep = { interval_minutes: source.interval_minutes };
  const lastRun = when(source.last_run_at);

  return (
    <li className="source card-item" aria-label={source.label}>
      <div className="source-head">
        <h2>{source.label}</h2>
        <span className={`chip source-state source-${source.blocked ? "blocked" : source.enabled ? "on" : "off"}`}>{state.label}</span>
      </div>
      <p className="card-sub">{source.description}</p>

      {source.blocked && (
        <div role="alert" className="notice">
          <p>
            <strong>Cette source a été arrêtée</strong> : {state.note ?? "blocage détecté"}. Le site a refusé les visites du robot.
            Insister peut aggraver le blocage ; ne la réactivez que si vous savez que le problème est réglé.
          </p>
          {confirming ? (
            <div className="actions">
              <button type="button" className="primary" disabled={busy} onClick={() => void save({ enabled: true, ...keep, confirm_unblock: true })}>
                Je comprends, réactiver {source.label}
              </button>
              <button type="button" disabled={busy} onClick={() => setConfirming(false)}>
                Annuler
              </button>
            </div>
          ) : (
            <button type="button" disabled={busy} onClick={() => setConfirming(true)}>
              Réactiver malgré le blocage…
            </button>
          )}
        </div>
      )}

      {!source.blocked && !source.configured && (
        <p className="hint">
          La clé de cette source n'est pas encore installée sur le serveur ({source.key_env.join(", ")}). Demandez à la personne qui
          gère l'installation de l'ajouter.
        </p>
      )}

      {!source.blocked && (
        <div className="source-controls">
          <div className="check">
            <input
              id={`source-${source.source}`}
              type="checkbox"
              checked={source.enabled}
              disabled={busy || (!source.configured && !source.enabled)}
              onChange={(e) => void save({ enabled: e.target.checked, ...keep })}
            />
            <label htmlFor={`source-${source.source}`}>Activer cette source</label>
          </div>
          <label>
            Fréquence de collecte
            <select
              value={effective}
              disabled={busy}
              onChange={(e) => void save({ enabled: source.enabled, interval_minutes: Number(e.target.value) })}
            >
              {options.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      <p className="card-date">{lastRun ? `Dernière collecte : ${lastRun}` : "Jamais collectée"}</p>
      {problem && (
        <p role="alert" className="error">
          {problem}
        </p>
      )}
    </li>
  );
}

type SaveBody = { enabled: boolean; interval_minutes: number | null; confirm_unblock?: boolean };

export function SourcesPage() {
  const api = useApi();
  const [sources, setSources] = useState<Source[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    api
      .GET("/sources")
      .then(unwrap)
      .then((list) => active && setSources(list))
      .catch((e: unknown) => active && setLoadError(e instanceof Error ? e.message : "Chargement impossible"));
    return () => {
      active = false;
    };
  }, [api]);

  /** Renvoie `null` si l'enregistrement a réussi, sinon le message à afficher sous la source. */
  async function save(source: string, body: SaveBody): Promise<string | null> {
    try {
      const updated = unwrap(await api.PUT("/sources/{source}", { params: { path: { source } }, body }));
      setSources((list) => list?.map((s) => (s.source === source ? updated : s)) ?? list);
      return null;
    } catch (failure) {
      return failure instanceof Error ? failure.message : "Enregistrement impossible";
    }
  }

  return (
    <section id="sources" aria-labelledby="sources-title">
      <h1 id="sources-title">Mes sources</h1>
      <p className="muted">
        Choisissez où le robot cherche des offres pour vous. Rien n'est collecté tant que vous n'avez pas activé une source, et
        chaque source utilise vos critères de recherche.
      </p>
      {loadError && (
        <p role="alert" className="error">
          {loadError}
        </p>
      )}
      {!sources && !loadError && <p role="status">Chargement…</p>}
      {sources && (
        <ul className="source-list" aria-label="Sources disponibles">
          {sources.map((s) => (
            <SourceCard key={s.source} source={s} onSave={(body) => save(s.source, body)} />
          ))}
        </ul>
      )}
    </section>
  );
}
