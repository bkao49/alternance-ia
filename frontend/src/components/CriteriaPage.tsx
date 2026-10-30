import { useEffect, useState, type FormEvent } from "react";

import { unwrap } from "../api/client";
import { useApi } from "../api/context";
import type { SearchPreferences } from "../api/types";

type Input = Omit<SearchPreferences, "updated_at">;
type ContractType = Input["contract_types"][number];
type Level = NonNullable<Input["education_level"]>;

const CONTRACTS: [ContractType, string][] = [
  ["internship", "Stage"],
  ["apprenticeship", "Alternance"],
  ["fixed_term", "CDD"],
  ["permanent", "CDI"],
  ["other", "Autre"],
];
const LEVELS: [Level, string][] = [
  ["bac", "Bac"],
  ["bac_plus_2", "Bac+2"],
  ["bac_plus_3", "Bac+3"],
  ["bac_plus_4", "Bac+4"],
  ["bac_plus_5", "Bac+5"],
  ["doctorate", "Doctorat"],
  ["other", "Autre"],
];

/** Un mot ou une expression par ligne : les lignes vides et les doublons disparaissent. */
export const toList = (text: string) => [...new Set(text.split("\n").map((line) => line.trim()).filter(Boolean))];

const uniqueLocations = <T extends { label: string; radius_km: number }>(items: T[]) =>
  items.filter((l, i) => items.findIndex((o) => o.label === l.label && o.radius_km === l.radius_km) === i);

type Draft = {
  keywords: string;
  excluded: string;
  locations: { label: string; radius: string }[];
  remote: boolean;
  contracts: ContractType[];
  startDate: string;
  duration: string;
  rhythm: string;
  level: string;
  salary: string;
};

const toDraft = (p: SearchPreferences): Draft => ({
  keywords: p.keywords.join("\n"),
  excluded: p.excluded_keywords.join("\n"),
  locations: p.locations.map((l) => ({ label: l.label, radius: String(l.radius_km) })),
  remote: p.remote_accepted,
  contracts: p.contract_types,
  startDate: p.start_date ?? "",
  duration: p.duration_months?.toString() ?? "",
  rhythm: p.alternance_rhythm ?? "",
  level: p.education_level ?? "",
  salary: p.min_salary_eur?.toString() ?? "",
});

const toInput = (d: Draft): Input => ({
  keywords: toList(d.keywords),
  excluded_keywords: toList(d.excluded),
  locations: uniqueLocations(
    d.locations
      .filter((l) => l.label.trim())
      .map((l) => ({ label: l.label.trim(), radius_km: l.radius === "" ? 30 : Math.round(Number(l.radius)) })),
  ),
  remote_accepted: d.remote,
  contract_types: d.contracts,
  start_date: d.startDate || null,
  duration_months: d.duration ? Math.round(Number(d.duration)) : null,
  alternance_rhythm: d.rhythm.trim() || null,
  education_level: (d.level || null) as Level | null,
  min_salary_eur: d.salary ? Math.round(Number(d.salary)) : null,
});

export function CriteriaPage() {
  const api = useApi();
  const [draft, setDraft] = useState<Draft | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    api
      .GET("/preferences")
      .then(unwrap)
      .then((p) => active && setDraft(toDraft(p)))
      .catch((e: unknown) => active && setLoadError(e instanceof Error ? e.message : "Chargement impossible"));
    return () => {
      active = false;
    };
  }, [api]);

  if (loadError) {
    return (
      <section aria-labelledby="criteria-title">
        <h1 id="criteria-title">Mes critères</h1>
        <p role="alert" className="error">{loadError}</p>
      </section>
    );
  }
  if (!draft) return <p role="status">Chargement…</p>;

  const set = (change: Partial<Draft>) => {
    setDraft({ ...draft, ...change });
    setSaved(false);
  };
  const setLocation = (index: number, change: Partial<Draft["locations"][number]>) =>
    set({ locations: draft.locations.map((l, i) => (i === index ? { ...l, ...change } : l)) });

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    setBusy(true);
    setError(null);
    try {
      setDraft(toDraft(unwrap(await api.PUT("/preferences", { body: toInput(draft) }))));
      setSaved(true);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Enregistrement impossible");
    }
    setBusy(false);
  }

  return (
    <section id="criteres" aria-labelledby="criteria-title">
      <h1 id="criteria-title">Mes critères</h1>
      <p className="muted">Ce que vous cherchez. Les collecteurs et le score s'en servent.</p>
      <form onSubmit={submit} className="form criteria" aria-busy={busy}>
        <fieldset disabled={busy} className="plain">
        <label>
          Métiers ou mots-clés (un par ligne)
          <textarea rows={4} maxLength={20 * 81} value={draft.keywords} onChange={(e) => set({ keywords: e.target.value })} />
        </label>

        <fieldset>
          <legend>Lieux</legend>
          {draft.locations.map((location, index) => (
            <div className="actions" key={index}>
              <label>
                Ville ou région{draft.locations.length > 1 ? ` (lieu ${index + 1})` : ""}
                <input maxLength={120} value={location.label} onChange={(e) => setLocation(index, { label: e.target.value })} />
              </label>
              <label>
                Rayon (km)
                <input
                  type="number"
                  min={0}
                  max={200}
                  value={location.radius}
                  onChange={(e) => setLocation(index, { radius: e.target.value })}
                />
              </label>
              <button
                type="button"
                aria-label={`Retirer le lieu ${index + 1}${location.label ? ` : ${location.label}` : ""}`}
                onClick={() => set({ locations: draft.locations.filter((_, i) => i !== index) })}
              >
                Retirer ce lieu
              </button>
            </div>
          ))}
          {draft.locations.length < 10 && (
            <button type="button" onClick={() => set({ locations: [...draft.locations, { label: "", radius: "30" }] })}>
              Ajouter un lieu
            </button>
          )}
        </fieldset>

        <div className="check">
          <input id="remote" type="checkbox" checked={draft.remote} onChange={(e) => set({ remote: e.target.checked })} />
          <label htmlFor="remote">Télétravail complet accepté, même hors de ces lieux</label>
        </div>

        <fieldset>
          <legend>Types de contrat</legend>
          {CONTRACTS.map(([value, label]) => (
            <div className="check" key={value}>
              <input
                id={`contract-${value}`}
                type="checkbox"
                checked={draft.contracts.includes(value)}
                onChange={(e) =>
                  set({ contracts: e.target.checked ? [...draft.contracts, value] : draft.contracts.filter((c) => c !== value) })
                }
              />
              <label htmlFor={`contract-${value}`}>{label}</label>
            </div>
          ))}
          <p className="muted">Aucun choix : tous les contrats.</p>
        </fieldset>

        <label>
          Date de début souhaitée
          <input type="date" value={draft.startDate} onChange={(e) => set({ startDate: e.target.value })} />
        </label>
        <label>
          Durée (mois)
          <input type="number" min={1} max={60} step={1} value={draft.duration} onChange={(e) => set({ duration: e.target.value })} />
        </label>
        <label>
          Rythme d'alternance (facultatif, à titre indicatif)
          <input maxLength={80} value={draft.rhythm} onChange={(e) => set({ rhythm: e.target.value })} />
        </label>
        <label>
          Niveau d'études
          <select value={draft.level} onChange={(e) => set({ level: e.target.value })}>
            <option value="">Non précisé</option>
            {LEVELS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Salaire minimal, brut par an en euros (facultatif)
          <input type="number" min={0} max={1000000} step={1} value={draft.salary} onChange={(e) => set({ salary: e.target.value })} />
        </label>
        <label>
          Mots à exclure (un par ligne)
          <textarea rows={3} maxLength={50 * 81} value={draft.excluded} onChange={(e) => set({ excluded: e.target.value })} />
        </label>

        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="actions">
          <button type="submit" className="primary" disabled={busy}>
            Enregistrer
          </button>
        </div>
        </fieldset>
        {/* Région toujours présente : un texte inséré dans une région vivante est annoncé. */}
        <p role="status" aria-live="polite">{saved ? "Critères enregistrés." : ""}</p>
      </form>
    </section>
  );
}
