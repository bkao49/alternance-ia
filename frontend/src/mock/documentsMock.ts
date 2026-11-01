import type { DocumentDraft, DocumentIssue, DocumentSection, FactCheck, Offer, ProfileFact } from "../api/types";

type Version = { number: number; origin: "generated" | "edited" | "restored"; created_at: string; sections: DocumentSection[] };
type Draft = { id: string; kind: "cv" | "cover_letter"; offer_id: string | null; title: string; versions: Version[] };
type Store = { facts: ProfileFact[]; offers: Offer[]; nextId: () => number };

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const error = (status: number, code: string, message: string) => json({ code, message }, status);

/** Faux backend des brouillons de CV et de lettres : mêmes routes et mêmes règles que le contrat, données fictives. */
export function createDocumentsMock(store: () => Store) {
  const drafts: Draft[] = [];

  const current = (d: Draft) => d.versions[d.versions.length - 1] as Version;

  function check(sections: DocumentSection[]): FactCheck {
    const { facts } = store();
    const issues: DocumentIssue[] = [];
    sections.forEach((section, s) =>
      section.bullets.forEach((bullet, b) => {
        const add = (code: DocumentIssue["code"], message: string) => issues.push({ section: s, bullet: b, code, message });
        if (bullet.fact_ids.length === 0) return add("no_fact_ids", "Cette ligne ne cite aucun fait : elle n'est pas justifiée.");
        const cited = bullet.fact_ids.map((id) => facts.find((f) => f.id === id));
        if (cited.some((f) => !f)) return add("unknown_fact", "Cette ligne cite un fait qui n'existe pas dans votre profil.");
        const pending = cited.find((f) => f?.status !== "validated");
        if (pending) return add("unvalidated_fact", `Le fait « ${pending.text.slice(0, 60)} » n'est pas encore validé.`);
        const evidence = cited.map((f) => `${f?.text} ${f?.technologies.join(" ")}`).join(" ").toLowerCase();
        if (/kubernetes/i.test(bullet.texte) && !evidence.includes("kubernetes")) {
          add("technology_not_in_facts", "La technologie « Kubernetes » n'apparaît dans aucun fait cité.");
        }
      }),
    );
    return { ok: issues.length === 0, verified: false, issues };
  }

  function out(d: Draft): DocumentDraft {
    const { facts } = store();
    const version = current(d);
    const used = new Set(version.sections.flatMap((s) => s.bullets.flatMap((b) => b.fact_ids)));
    return {
      id: d.id,
      kind: d.kind,
      offer_id: d.offer_id,
      title: d.title,
      current_version: version.number,
      updated_at: version.created_at,
      sections: version.sections,
      check: check(version.sections),
      diff: {
        lines: version.sections.flatMap((section, s) =>
          section.bullets.map((bullet, b) => {
            const cited = bullet.fact_ids.flatMap((id) => facts.find((f) => f.id === id) ?? []);
            const same = cited.length === 1 && cited[0]?.text === bullet.texte;
            return { section: s, bullet: b, status: same ? ("same" as const) : ("reformulated" as const), master_text: cited.map((f) => f.text).join(" ; ") };
          }),
        ),
        omitted_fact_ids: facts.filter((f) => f.status === "validated" && !used.has(f.id)).map((f) => f.id),
      },
    };
  }

  function compose(kind: "cv" | "cover_letter", offer: Offer | undefined): DocumentSection[] | null {
    const facts = store().facts.filter((f) => f.status === "validated");
    if (facts.length < 3 || !facts.some((f) => ["experience", "education", "project"].includes(f.kind))) return null;
    const lines = (kinds: string[]) => facts.filter((f) => kinds.includes(f.kind)).map((f) => ({ texte: f.text, fact_ids: [f.id] }));
    if (kind === "cover_letter") {
      const [first, second] = facts;
      return [
        {
          section: "Lettre",
          bullets: [
            { texte: `Votre offre « ${offer?.title ?? "poste"} » chez ${offer?.company ?? "votre entreprise"} correspond à mon parcours : ${first?.text}.`, fact_ids: [first?.id ?? ""] },
            { texte: `${second?.text}.`, fact_ids: [second?.id ?? ""] },
          ],
        },
      ];
    }
    const skills = facts.filter((f) => f.kind === "skill");
    return [
      { section: "Expérience", bullets: lines(["experience", "project"]) },
      { section: "Formation", bullets: lines(["education"]) },
      { section: "Compétences", bullets: skills.length ? [{ texte: skills.map((f) => f.text).join(", "), fact_ids: skills.map((f) => f.id) }] : [] },
    ].filter((s) => s.bullets.length > 0);
  }

  function push(d: Draft, origin: Version["origin"], sections: DocumentSection[]) {
    d.versions.push({ number: current(d).number + 1, origin, created_at: new Date().toISOString(), sections });
  }

  return function handle(method: string, path: string, query: string, body: Record<string, unknown>): Response | undefined {
    const route = /^\/documents(?:\/([^/]+?))?(?:\/(versions|restore|check|pdf))?$/.exec(path);
    if (!route) return undefined;
    const [, id, action] = route;
    const s = store();
    if (!id && method === "GET") {
      const wanted = new URLSearchParams(query).get("offer_id");
      return json(drafts.filter((d) => !wanted || d.offer_id === wanted).map((d) => ({ id: d.id, kind: d.kind, offer_id: d.offer_id, title: d.title, current_version: current(d).number, updated_at: current(d).created_at })));
    }
    if (id === "generate" && method === "POST") {
      const kind = body.kind as "cv" | "cover_letter";
      const offer = s.offers.find((o) => o.id === body.offer_id);
      if (kind === "cover_letter" && !body.offer_id) return error(422, "validation_error", "Une lettre a besoin d'une offre");
      if (body.offer_id && !offer) return error(404, "not_found", "Offre introuvable");
      const sections = compose(kind, offer);
      if (!sections) return error(409, "not_enough_facts", "Il faut au moins 3 faits validés, dont une expérience, une formation ou un projet");
      let draft = drafts.find((d) => d.kind === kind && d.offer_id === (offer?.id ?? null));
      if (draft) push(draft, "generated", sections);
      else {
        draft = { id: `draft-${s.nextId()}`, kind, offer_id: offer?.id ?? null, title: offer?.title ?? "CV général", versions: [{ number: 1, origin: "generated", created_at: new Date().toISOString(), sections }] };
        drafts.unshift(draft);
      }
      return json(out(draft), 201);
    }
    const draft = drafts.find((d) => d.id === id);
    if (!draft) return error(404, "not_found", "Brouillon introuvable");
    if (!action && method === "GET") return json(out(draft));
    if (!action && method === "DELETE") {
      drafts.splice(drafts.indexOf(draft), 1);
      return new Response(null, { status: 204 });
    }
    if (!action && method === "PUT") {
      if (body.base_version !== current(draft).number) return error(409, "version_conflict", "Le brouillon a changé depuis votre dernière lecture");
      const sections = (body.sections as { section: string; bullets: { texte: string; fact_ids: string[]; manual?: boolean }[] }[]).map((section) => ({
        section: section.section,
        bullets: section.bullets.map((bullet) => {
          if (!bullet.manual) return { texte: bullet.texte, fact_ids: bullet.fact_ids };
          const made: ProfileFact = { id: `fact-${s.nextId()}`, kind: "other", text: bullet.texte, start_date: null, end_date: null, technologies: [], source: "Ajout manuel dans un CV", status: "proposed", created_at: new Date().toISOString() };
          s.facts.unshift(made);
          return { texte: bullet.texte, fact_ids: [made.id] };
        }),
      }));
      push(draft, "edited", sections);
      return json(out(draft));
    }
    if (action === "versions" && method === "GET") return json([...draft.versions].reverse().map(({ number, origin, created_at }) => ({ number, origin, created_at })));
    if (action === "restore" && method === "POST") {
      const version = draft.versions.find((v) => v.number === body.version);
      if (!version) return error(404, "not_found", "Version introuvable");
      push(draft, "restored", structuredClone(version.sections));
      return json(out(draft));
    }
    if (action === "check" && method === "POST") {
      const result = check(current(draft).sections);
      return json(body.verify && result.ok ? { ...result, verified: true } : result);
    }
    if (action === "pdf" && method === "GET") {
      if (!check(current(draft).sections).ok) return error(409, "check_failed", "Le contrôle factuel n'est pas vert");
      return new Response("%PDF-1.4\n% document fictif de démonstration\n", { status: 200, headers: { "Content-Type": "application/pdf" } });
    }
    return undefined;
  };
}
