import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiFailure, unwrap } from "../api/client";
import { useApi } from "../api/context";
import type {
  DocumentDraft,
  DocumentDraftSummary,
  DocumentVersion,
  FactCheck,
  Offer,
  ProfileFact,
} from "../api/types";

type Target = "cv" | "cover_letter" | "general";
const TARGETS: [Target, string][] = [
  ["cv", "CV adapté à l'offre"],
  ["cover_letter", "Lettre de motivation"],
  ["general", "CV général amélioré"],
];
const ORIGIN = { generated: "générée", edited: "modifiée", restored: "restaurée" } as const;
const short = (text: string) => (text.length > 70 ? `${text.slice(0, 67)}…` : text);

/** Une ligne en cours d'édition : `manual` = écrite ici, elle deviendra un fait à valider à l'enregistrement. */
type Line = { texte: string; fact_ids: string[]; manual: boolean };
type Block = { section: string; lines: Line[] };

const toBlocks = (draft: DocumentDraft): Block[] =>
  draft.sections.map((s) => ({ section: s.section, lines: s.bullets.map((b) => ({ texte: b.texte, fact_ids: b.fact_ids, manual: false })) }));

const failureText = (failure: unknown) => (failure instanceof Error ? failure.message : "Action impossible");

export function PreparePage({ offerId }: { offerId: string }) {
  const api = useApi();
  const [offer, setOffer] = useState<Offer | null>(null);
  const [facts, setFacts] = useState<ProfileFact[]>([]);
  const [summaries, setSummaries] = useState<DocumentDraftSummary[]>([]);
  const [target, setTarget] = useState<Target>("cv");
  const [draft, setDraft] = useState<DocumentDraft | null>(null);
  const [versions, setVersions] = useState<DocumentVersion[]>([]);
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [phase, setPhase] = useState<"loading" | "ready" | "error">("loading");
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [review, setReview] = useState<FactCheck | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const factById = useMemo(() => new Map(facts.map((f) => [f.id, f])), [facts]);
  const original = useMemo(() => JSON.stringify(draft ? toBlocks(draft) : []), [draft]);
  const dirty = draft !== null && JSON.stringify(blocks) !== original;
  const blank = blocks.some((b) => b.lines.some((l) => !l.texte.trim()));
  const check = review ?? draft?.check ?? null;

  const show = useCallback(async (id: string) => {
    const [next, history] = await Promise.all([
      api.GET("/documents/{documentId}", { params: { path: { documentId: id } } }).then(unwrap),
      api.GET("/documents/{documentId}/versions", { params: { path: { documentId: id } } }).then(unwrap),
    ]);
    setDraft(next);
    setVersions(history);
    setBlocks(toBlocks(next));
    setReview(null);
  }, [api]);

  /** Affiche le brouillon de ce document pour cette offre, ou rien s'il n'existe pas encore. */
  const open = useCallback(async (which: Target, list: DocumentDraftSummary[]) => {
    const found = list.find((d) => (which === "general" ? d.kind === "cv" && d.offer_id === null : d.kind === which && d.offer_id === offerId));
    if (found) return show(found.id);
    setDraft(null);
    setVersions([]);
    setBlocks([]);
    setReview(null);
  }, [offerId, show]);

  const refreshFacts = useCallback(async () => setFacts(unwrap(await api.GET("/profile/facts", { params: { query: {} } }))), [api]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const [found, list, all] = await Promise.all([
          api.GET("/offers/{offerId}", { params: { path: { offerId } } }).then(unwrap),
          api.GET("/documents", { params: { query: {} } }).then(unwrap),
          api.GET("/profile/facts", { params: { query: {} } }).then(unwrap),
        ]);
        if (!active) return;
        setOffer(found);
        setSummaries(list);
        setFacts(all);
        await open("cv", list);
        if (active) setPhase("ready");
      } catch (failure) {
        if (!active) return;
        setProblem(failureText(failure));
        setPhase("error");
      }
    })();
    return () => {
      active = false;
    };
  }, [api, offerId, open, reloadKey]);

  function choose(which: Target) {
    setTarget(which);
    setProblem(null);
    open(which, summaries).catch((failure) => setProblem(failureText(failure)));
  }

  async function act(work: () => Promise<void>) {
    setBusy(true);
    setProblem(null);
    try {
      await work();
    } catch (failure) {
      setProblem(failure instanceof ApiFailure && failure.code === "not_enough_facts"
        ? `${failure.message}. Complétez et validez vos faits dans « Mon profil ».` : failureText(failure));
    } finally {
      setBusy(false);
    }
  }

  const refreshList = async () => setSummaries(unwrap(await api.GET("/documents", { params: { query: {} } })));

  const generate = () =>
    act(async () => {
      const body = { kind: target === "cover_letter" ? ("cover_letter" as const) : ("cv" as const), offer_id: target === "general" ? null : offerId };
      const created = unwrap(await api.POST("/documents/generate", { body }));
      await refreshList();
      await show(created.id);
    });

  const save = () =>
    act(async () => {
      if (!draft) return;
      const sections = blocks.map((b) => ({
        section: b.section,
        bullets: b.lines.map((l) => ({ texte: l.texte.trim(), fact_ids: l.manual ? [] : l.fact_ids, manual: l.manual })),
      }));
      unwrap(await api.PUT("/documents/{documentId}", { params: { path: { documentId: draft.id } }, body: { base_version: draft.current_version, sections } }));
      await Promise.all([show(draft.id), refreshFacts()]);
    });

  const restore = (version: number) =>
    act(async () => {
      if (!draft) return;
      unwrap(await api.POST("/documents/{documentId}/restore", { params: { path: { documentId: draft.id } }, body: { version } }));
      await show(draft.id);
    });

  const validateFact = (id: string) =>
    act(async () => {
      unwrap(await api.POST("/profile/facts/{factId}/validate", { params: { path: { factId: id } } }));
      await Promise.all([refreshFacts(), draft ? show(draft.id) : Promise.resolve()]);
    });

  const verify = () =>
    act(async () => {
      if (!draft) return;
      setReview(unwrap(await api.POST("/documents/{documentId}/check", { params: { path: { documentId: draft.id } }, body: { verify: true } })));
    });

  const exportPdf = () =>
    act(async () => {
      if (!draft) return;
      const blob = unwrap(await api.GET("/documents/{documentId}/pdf", { params: { path: { documentId: draft.id } }, parseAs: "blob" }));
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = target === "cover_letter" ? "lettre.pdf" : "cv.pdf";
      link.click();
      URL.revokeObjectURL(link.href);
    });

  const edit = (b: number, l: number, change: Partial<Line>) =>
    setBlocks((before) => before.map((block, i) => (i !== b ? block : { ...block, lines: block.lines.map((line, j) => (j === l ? { ...line, ...change } : line)) })));
  const move = (b: number, l: number, by: number) =>
    setBlocks((before) =>
      before.map((block, i) => {
        if (i !== b || l + by < 0 || l + by >= block.lines.length) return block;
        const lines = [...block.lines];
        [lines[l], lines[l + by]] = [lines[l + by] as Line, lines[l] as Line];
        return { ...block, lines };
      }),
    );
  const remove = (b: number, l: number) =>
    setBlocks((before) => before.map((block, i) => (i === b ? { ...block, lines: block.lines.filter((_, j) => j !== l) } : block)));
  const add = (b: number) =>
    setBlocks((before) => before.map((block, i) => (i === b ? { ...block, lines: [...block.lines, { texte: "", fact_ids: [], manual: true }] } : block)));

  if (phase === "loading") return <p role="status">Chargement…</p>;
  if (phase === "error") {
    return (
      <p role="alert" className="error">
        {problem} <button type="button" onClick={() => { setPhase("loading"); setProblem(null); setReloadKey((k) => k + 1); }}>Réessayer</button>
      </p>
    );
  }

  const issuesOf = (s: number, b: number) => (dirty || review ? [] : (draft?.check.issues ?? []).filter((i) => i.section === s && i.bullet === b));
  const diffOf = (s: number, b: number) => draft?.diff.lines.find((d) => d.section === s && d.bullet === b);

  return (
    <>
      <h1>Préparer la candidature</h1>
      <p className="muted">
        {offer?.title} · {offer?.company}. Chaque ligne vient de vos faits validés : rien n'est inventé, rien n'est envoyé.
      </p>
      <div className="segmented" role="group" aria-label="Document à préparer">
        {TARGETS.map(([key, label]) => (
          <button key={key} type="button" aria-pressed={target === key} disabled={busy || (dirty && target !== key)} onClick={() => choose(key)}>
            {label}
          </button>
        ))}
      </div>
      {problem && (
        <p role="alert" className="error">
          {problem}
        </p>
      )}

      <div className="actions prepare-actions">
        <button type="button" className="primary" disabled={busy || dirty} onClick={() => void generate()}>
          {draft ? "Régénérer" : "Générer"}
        </button>
        {draft && (
          <>
            <button type="button" disabled={busy || !dirty || blank} onClick={() => void save()}>
              Enregistrer mes modifications
            </button>
            <button type="button" disabled={busy || dirty || !check?.ok} onClick={() => void verify()}>
              Faire relire par l'IA
            </button>
            <button type="button" disabled={busy || dirty || !draft.check.ok} onClick={() => void exportPdf()}>
              Exporter en PDF
            </button>
          </>
        )}
      </div>

      {!draft && <p className="muted">Aucun document pour l'instant. « Générer » le rédige à partir de vos faits validés.</p>}

      {draft && check && (
        <section aria-label="Contrôle factuel" className={`factcheck ${check.ok && !dirty ? "is-ok" : "is-bad"}`} aria-live="polite">
          {dirty ? (
            <p>Modifications non enregistrées : enregistrez pour relancer le contrôle factuel.</p>
          ) : check.ok ? (
            <p>
              <strong>Contrôle factuel : tout est justifié.</strong> {check.verified ? "Relu aussi par l'IA, sans écart." : "Chaque ligne cite des faits validés."}
            </p>
          ) : (
            <>
              <p>
                <strong>Contrôle factuel : {check.issues.length > 1 ? `${check.issues.length} lignes rejetées` : "1 ligne rejetée"}.</strong> Le document ne peut pas être exporté.
              </p>
              <ul>
                {check.issues.map((issue, i) => (
                  <li key={i}>
                    Ligne {issue.bullet + 1} de « {blocks[issue.section]?.section ?? draft.sections[issue.section]?.section} » : {issue.message}
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}

      {draft && (
        <>
          {blocks.map((block, b) => (
            <section key={b} aria-label={block.section} className="draft-section">
              <h2>{block.section}</h2>
              <ol className="draft-lines">
                {block.lines.map((line, l) => {
                  const diff = diffOf(b, l);
                  const name = `${block.section}, ligne ${l + 1}`;
                  return (
                    <li key={`${b}-${l}`}>
                      <textarea aria-label={`Texte : ${name}`} rows={2} maxLength={600} value={line.texte} onChange={(e) => edit(b, l, { texte: e.target.value })} />
                      <div className="line-facts">
                        {line.manual ? (
                          <span className="chip">Ajoutée à la main : elle deviendra un fait à valider</span>
                        ) : (
                          line.fact_ids.map((id) => {
                            const fact = factById.get(id);
                            return (
                              <span key={id} className="chip">
                                {fact ? `Fait : ${short(fact.text)}` : "Fait inconnu"}
                                {fact?.status === "proposed" && (
                                  <>
                                    {" · à valider "}
                                    <button type="button" className="link" disabled={busy || dirty} onClick={() => void validateFact(id)}>
                                      Valider ce fait
                                    </button>
                                  </>
                                )}
                              </span>
                            );
                          })
                        )}
                        {!dirty && diff && !line.manual && (
                          <span className="muted">{diff.status === "same" ? "Identique au CV maître" : `Reformulée. CV maître : ${short(diff.master_text)}`}</span>
                        )}
                      </div>
                      {issuesOf(b, l).map((issue, i) => (
                        <p key={i} role="alert" className="error">
                          {issue.message}
                        </p>
                      ))}
                      <div className="line-actions">
                        <button type="button" disabled={l === 0} onClick={() => move(b, l, -1)} aria-label={`Monter : ${name}`}>
                          Monter
                        </button>
                        <button type="button" disabled={l === block.lines.length - 1} onClick={() => move(b, l, 1)} aria-label={`Descendre : ${name}`}>
                          Descendre
                        </button>
                        <button type="button" onClick={() => remove(b, l)} aria-label={`Retirer : ${name}`}>
                          Retirer
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ol>
              <button type="button" onClick={() => add(b)}>
                Ajouter une ligne à « {block.section} »
              </button>
            </section>
          ))}
          {draft.diff.omitted_fact_ids.length > 0 && !dirty && (
            <p className="muted">
              {draft.diff.omitted_fact_ids.length} fait{draft.diff.omitted_fact_ids.length > 1 ? "s validés ne sont" : " validé n'est"} pas utilisé{draft.diff.omitted_fact_ids.length > 1 ? "s" : ""} dans cette version.
            </p>
          )}

          <section aria-label="Versions" className="draft-versions">
            <h2>Versions</h2>
            <ol className="history">
              {versions.map((version) => (
                <li key={version.number}>
                  <strong>Version {version.number}</strong> {ORIGIN[version.origin]} le {new Date(version.created_at).toLocaleString("fr-FR")}
                  {version.number === draft.current_version ? (
                    <span className="chip">Version courante</span>
                  ) : (
                    <button type="button" disabled={busy || dirty} onClick={() => void restore(version.number)} aria-label={`Restaurer la version ${version.number}`}>
                      Restaurer
                    </button>
                  )}
                </li>
              ))}
            </ol>
          </section>
        </>
      )}
    </>
  );
}
