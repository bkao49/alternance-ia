import type { Application, ApplicationEvent, DashboardStats, ProfileCv, ProfileFact, Mailbox, SearchPreferences, Source, Status } from "../api/types";
import { createDocumentsMock } from "./documentsMock";
import { seedApplications, seedOffers, seedStatuses } from "./data";
import { DEMO } from "./demoInfo";

const DEMO_USER = { id: "user-demo", email: DEMO.email };
const REPLY_KEYS = ["interview", "rejected", "offer_received"];
const PREPARED_KEYS = ["human_review", "sent", "waiting", "interview", "rejected", "offer_received"];

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const error = (status: number, code: string, message: string) => json({ code, message }, status);

/** Faux backend en mémoire : mêmes routes et mêmes règles que le contrat (dont « Envoyée » par confirmation). */
export function createMockFetch(options: { facts?: ProfileFact[] } = {}) {
  const statuses: Status[] = seedStatuses();
  const applications: Application[] = seedApplications(statuses);
  const offers = seedOffers(applications);
  const events = new Map<string, ApplicationEvent[]>();
  let signedIn = false;
  let facts: ProfileFact[] = options.facts ?? [];
  let cv: { info: ProfileCv; readyAt: number } | null = null;
  let preferences: SearchPreferences = {
    keywords: [], locations: [], remote_accepted: false, contract_types: [], start_date: null,
    duration_months: null, alternance_rhythm: null, education_level: null, min_salary_eur: null,
    excluded_keywords: [], updated_at: null,
  };
  const base = { enabled: false, interval_minutes: null, default_interval_minutes: 120, blocked: false, blocked_cause: null, blocked_at: null, last_run_at: null, last_success_at: null };
  const sources: Source[] = [
    { ...base, source: "france_travail", label: "France Travail", description: "L'API officielle de l'État : offres de tous contrats et de tous métiers.", key_env: ["FRANCE_TRAVAIL_CLIENT_ID", "FRANCE_TRAVAIL_CLIENT_SECRET"], configured: false },
    { ...base, source: "lba", label: "La Bonne Alternance", description: "L'API officielle des offres en alternance et des entreprises qui recrutent.", key_env: ["LBA_API_TOKEN"], configured: true, enabled: true, last_run_at: new Date(Date.now() - 46 * 60_000).toISOString() },
    { ...base, source: "adzuna", label: "Adzuna", description: "Un agrégateur d'annonces avec une API gratuite : stages, CDD, CDI et alternance.", key_env: ["ADZUNA_APP_ID", "ADZUNA_APP_KEY"], configured: true, blocked: true, blocked_cause: "blocage détecté (403)", blocked_at: new Date(Date.now() - 300 * 60_000).toISOString() },
    { ...base, source: "web", label: "Pages carrières (robot web)", description: "Les pages emploi des entreprises que vous indiquez : le robot lit les offres qu'elles publient.", key_env: [], configured: false },
    { ...base, source: "email", label: "Alertes e-mail (LinkedIn, Indeed…)", description: "Les alertes emploi que vous créez vous-même, reçues dans une boîte e-mail dédiée que le robot lit.", key_env: [], configured: false },
  ];
  let mailbox: Mailbox = { configured: false };
  let webPages: string[] = [];
  let nextId = applications.length + 1;
  const documents = createDocumentsMock(() => ({ facts, offers, nextId: () => nextId++ }));

  /** Faits fictifs « trouvés » dans un CV fictif ; le faux backend ne lit jamais le fichier reçu. */
  function proposeDemoFacts(): ProfileFact[] {
    const base = { end_date: null, source: "CV", status: "proposed" as const, created_at: new Date().toISOString() };
    return [
      { ...base, id: `fact-${nextId++}`, kind: "experience", text: "Stage de data analyst chez Acme (fictif)", start_date: "2025-03-01", technologies: ["Python", "SQL"] },
      { ...base, id: `fact-${nextId++}`, kind: "education", text: "Master Data Science, Université Imaginaire (fictif)", start_date: "2024-09-01", technologies: [] },
      { ...base, id: `fact-${nextId++}`, kind: "skill", text: "Python", start_date: null, technologies: ["Python"] },
      { ...base, id: `fact-${nextId++}`, kind: "language", text: "Anglais (B2)", start_date: null, technologies: [] },
    ];
  }

  function cvState(): ProfileCv | null {
    if (cv && cv.info.status === "processing" && Date.now() >= cv.readyAt) {
      const found = proposeDemoFacts();
      facts = [...found, ...facts];
      cv.info = { ...cv.info, status: "done", facts_proposed: found.length };
    }
    return cv?.info ?? null;
  }

  const byKey = (key: string) => statuses.find((s) => s.system_key === key) as Status;
  const reached = (keys: string[]) => applications.filter((a) => keys.includes(a.status.system_key ?? "")).length;

  function record(application: Application, from: string | null, to: string, comment: string | null) {
    const list = events.get(application.id) ?? [];
    const event: ApplicationEvent = {
      id: `event-${nextId++}`,
      from_status: from,
      to_status: to,
      actor: "user",
      comment,
      occurred_at: new Date().toISOString(),
    };
    events.set(application.id, [event, ...list]);
  }

  function stats(): DashboardStats {
    const sent = applications.filter((a) => a.sent_at).length;
    const ratio = (n: number) => (sent === 0 ? null : n / sent);
    return {
      counts: {
        detected: 42,
        analyzed: 31,
        relevant: offers.filter((o) => (o.score ?? 0) >= 3.5).length,
        prepared: reached(PREPARED_KEYS),
        to_validate: reached(["human_review"]),
        sent,
        replies: reached(REPLY_KEYS),
        interviews: reached(["interview"]),
        rejections: reached(["rejected"]),
        offers: reached(["offer_received"]),
      },
      conversion: {
        sent_to_reply: ratio(reached(REPLY_KEYS)),
        sent_to_interview: ratio(reached(["interview"])),
        sent_to_offer: ratio(reached(["offer_received"])),
      },
    };
  }

  return async function mockFetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname.replace(/^\/api/, "");
    const method = request.method;
    const cvMatch = /^\/profile\/cv(\/download-link)?$/.exec(path);
    const hasBody = !cvMatch && (method === "POST" || method === "PATCH" || method === "PUT");
    const factMatch = /^\/profile\/facts(?:\/([^/]+))?$/.exec(path);
    const body = hasBody ? ((await request.json().catch(() => ({}))) as Record<string, unknown>) : {};

    if (method === "POST" && path === "/auth/login") {
      if (body.password !== DEMO.password) return error(401, "invalid_credentials", "Identifiants invalides");
      signedIn = true;
      document.cookie = "csrf_token=demo; path=/";
      return json(DEMO_USER);
    }
    if (method === "POST" && path === "/auth/logout") {
      signedIn = false;
      return new Response(null, { status: 204 });
    }
    if (!signedIn) return error(401, "unauthorized", "Non connecté");

    const handled = documents(method, path, url.search, body);
    if (handled) return handled;
    const offerMatch = /^\/offers\/([^/]+)$/.exec(path);
    if (method === "GET" && offerMatch) {
      const offer = offers.find((o) => o.id === offerMatch[1]);
      return offer ? json({ ...offer, description_text: "Annonce fictive de démonstration." }) : error(404, "not_found", "Offre introuvable");
    }
    if (method === "GET" && path === "/auth/me") return json(DEMO_USER);
    if (method === "GET" && path === "/statuses") return json(statuses);
    if (method === "GET" && path === "/dashboard/stats") return json(stats());
    if (method === "GET" && path === "/preferences") return json(preferences);
    if (cvMatch) {
      const link = Boolean(cvMatch[1]);
      if (method === "POST" && !link) {
        const raw = request.headers.get("content-type")?.startsWith("multipart/form-data") ? await request.text() : "";
        const name = /filename="([^"]*)"/.exec(raw)?.[1]; // le faux backend ne lit jamais le contenu du fichier
        if (name === undefined) return error(422, "validation_error", "Un fichier est attendu");
        const file = { name, size: raw.length };
        if (file.size > 5 * 1024 * 1024) return error(413, "file_too_large", "Le fichier dépasse 5 Mo");
        facts = facts.filter((f) => f.status !== "proposed");
        cv = {
          readyAt: Date.now() + 1200,
          info: { id: `cv-${nextId++}`, original_name: file.name, file_type: /\.docx$/i.test(file.name) ? "docx" : "pdf", size_bytes: Math.max(file.size, 1), status: "processing", error_code: null, facts_proposed: 0, created_at: new Date().toISOString() },
        };
        return json(cv.info, 202);
      }
      const current = cvState();
      if (!current) return error(404, "not_found", "Aucun CV déposé");
      if (method === "GET" && !link) return json(current);
      if (method === "DELETE" && !link) {
        cv = null;
        facts = facts.filter((f) => f.source !== "CV");
        return new Response(null, { status: 204 });
      }
      if (method === "POST" && link) return json({ url: "/profile/cv/file/demo", expires_at: new Date(Date.now() + 60000).toISOString() });
    }
    if (path === "/profile/facts/bulk" && method === "POST") {
      const { action, ids } = body as { action: "validate" | "reject"; ids: string[] };
      const targets = facts.filter((f) => f.status === "proposed" && ids.includes(f.id));
      facts = action === "reject" ? facts.filter((f) => !targets.includes(f)) : facts.map((f) => (targets.includes(f) ? { ...f, status: "validated" as const } : f));
      return json({ processed: targets.length });
    }
    const decision = /^\/profile\/facts\/([^/]+)\/(validate|reject)$/.exec(path);
    if (decision && method === "POST") {
      const target = facts.find((f) => f.id === decision[1]);
      if (!target) return error(404, "not_found", "Fait introuvable");
      if (decision[2] === "reject") {
        if (target.status === "validated") return error(409, "already_validated", "Ce fait est déjà validé");
        facts = facts.filter((f) => f !== target);
        return new Response(null, { status: 204 });
      }
      const validated = { ...target, status: "validated" as const };
      facts = facts.map((f) => (f === target ? validated : f));
      return json(validated);
    }
    if (factMatch) {
      const id = factMatch[1];
      if (!id && method === "GET") return json(facts);
      if (!id && method === "POST") {
        const created = { ...(body as Omit<ProfileFact, "id" | "created_at">), id: `fact-${nextId++}`, created_at: new Date().toISOString(), status: "validated" as const };
        facts = [created, ...facts];
        return json(created, 201);
      }
      const current = facts.find((f) => f.id === id);
      if (!current) return error(404, "not_found", "Fait introuvable");
      if (method === "PUT") {
        const changed = { ...current, ...(body as object) } as ProfileFact;
        facts = facts.map((f) => (f.id === id ? changed : f));
        return json(changed);
      }
      if (method === "DELETE") {
        facts = facts.filter((f) => f.id !== id);
        return new Response(null, { status: 204 });
      }
    }
    if (method === "GET" && path === "/sources") return json(sources);
    if (path === "/sources/email/mailbox" && method === "GET") return json(mailbox);
    if (path === "/sources/email/mailbox" && method === "PUT") {
      const input = body as { host: string; username: string; password?: string; folder?: string };
      if (/^(localhost|[\d.]+|[^.]+)$/i.test(input.host) || /\.(local|internal)$/i.test(input.host)) {
        return error(422, "validation_error", "Serveur refusé : adresse locale ou interne refusée.");
      }
      if (!input.password && !mailbox.configured) return error(422, "validation_error", "Le mot de passe d'application est obligatoire.");
      mailbox = { configured: true, host: input.host, port: 993, username: input.username, folder: input.folder ?? "INBOX", updated_at: new Date().toISOString() };
      const email = sources.findIndex((s) => s.source === "email");
      sources[email] = { ...sources[email]!, configured: true };
      return json(mailbox);
    }
    if (path === "/sources/email/mailbox" && method === "DELETE") {
      mailbox = { configured: false };
      const email = sources.findIndex((s) => s.source === "email");
      sources[email] = { ...sources[email]!, configured: false, enabled: false };
      return new Response(null, { status: 204 });
    }
    if (path === "/sources/email/mailbox/test" && method === "POST") {
      if (!mailbox.configured) return error(404, "not_found", "Aucune boîte enregistrée.");
      const tested_at = new Date().toISOString();
      mailbox = { ...mailbox, last_test_at: tested_at, last_test_ok: true };
      return json({ ok: true, message: "Connexion réussie : la boîte et le dossier sont lisibles.", tested_at });
    }
    if (path === "/sources/web/pages" && method === "GET") return json({ urls: webPages, max: 10 });
    if (path === "/sources/web/pages" && method === "PUT") {
      const urls: string[] = [];
      for (const [index, raw] of ((body as { urls: string[] }).urls).entries()) {
        const clean = raw.trim().split("#")[0] ?? "";
        const local = /^https?:\/\/(localhost|[\d.]+|\[.*\]|[^./]+)([:/]|$)/i.test(clean);
        if (!/^https?:\/\/[^\s/]+\.[a-z]{2,}(\/|$)/i.test(clean) || local) {
          return error(422, "validation_error", `Page ${index + 1} : adresse invalide ou locale refusée.`);
        }
        if (/linkedin\.com|indeed\./i.test(clean)) {
          return error(422, "validation_error", `Page ${index + 1} : site fermé aux robots : créez plutôt une alerte e-mail (écran « Mes sources »).`);
        }
        if (!urls.includes(clean)) urls.push(clean);
      }
      if (urls.length > 10) return error(422, "validation_error", "10 pages au plus.");
      webPages = urls;
      const web = sources.findIndex((s) => s.source === "web");
      sources[web] = { ...sources[web]!, configured: urls.length > 0, enabled: urls.length > 0 && sources[web]!.enabled };
      return json({ urls: webPages, max: 10 });
    }
    const sourceMatch = /^\/sources\/([a-z_]+)$/.exec(path);
    if (method === "PUT" && sourceMatch) {
      const index = sources.findIndex((s) => s.source === sourceMatch[1]);
      const current = sources[index];
      if (!current) return error(404, "not_found", "Source inconnue");
      const { enabled, interval_minutes, confirm_unblock } = body as { enabled: boolean; interval_minutes: number | null; confirm_unblock?: boolean };
      if (enabled && current.blocked && !confirm_unblock) {
        return error(409, "source_blocked", `Cette source a été arrêtée : ${current.blocked_cause}. La réactiver peut aggraver le blocage ; confirmez pour continuer.`);
      }
      if (enabled && !current.configured) return error(409, "source_not_configured", current.source === "web" ? "Ajoutez d'abord au moins une page à lire." : current.source === "email" ? "Enregistrez d'abord votre boîte e-mail dédiée." : "La clé de cette source n'est pas configurée sur le serveur.");
      const unblock = enabled && current.blocked;
      sources[index] = {
        ...current, enabled, interval_minutes,
        ...(unblock ? { blocked: false, blocked_cause: null, blocked_at: null } : {}),
      };
      return json(sources[index]);
    }
    if (method === "PUT" && path === "/preferences") {
      preferences = { ...(body as Omit<SearchPreferences, "updated_at">), updated_at: new Date().toISOString() };
      return json(preferences);
    }

    if (method === "GET" && path === "/offers") {
      const page = Number(url.searchParams.get("page") ?? 1);
      const size = Number(url.searchParams.get("page_size") ?? 25);
      const kinds = url.searchParams.getAll("contract_type");
      const min = Number(url.searchParams.get("min_score") ?? 0);
      const matching = offers.filter(
        (o) => (o.score ?? 0) >= min && (kinds.length === 0 || kinds.includes(o.contract_type ?? "")),
      );
      return json({ items: matching.slice((page - 1) * size, page * size), page, page_size: size, total: matching.length });
    }
    if (method === "GET" && path === "/bot/status") {
      const ago = (minutes: number) => new Date(Date.now() - minutes * 60_000).toISOString();
      return json({
        next_run_at: new Date(Date.now() + 134 * 60_000).toISOString(),
        sources: [
          { source: "source_a", state: "ok", last_run_at: ago(46), offers_found: 61, offers_new: 4 },
          { source: "source_b", state: "ok", last_run_at: ago(45), offers_found: 38, offers_new: 2 },
          { source: "site_carrieres", state: "blocked", cause: "Blocage détecté (403), source arrêtée" },
        ],
        activity: [
          { at: ago(45), source: "source_b", outcome: "done", message: "38 offres lues, 2 nouvelles" },
          { at: ago(46), source: "source_a", outcome: "done", message: "61 offres lues, 4 nouvelles" },
          { at: ago(300), source: "site_carrieres", outcome: "blocked", message: "Blocage détecté (403), source arrêtée" },
        ],
      });
    }
    if (method === "GET" && path === "/applications") {
      const page = Number(url.searchParams.get("page") ?? 1);
      const size = Number(url.searchParams.get("page_size") ?? 25);
      const items = applications.slice((page - 1) * size, page * size);
      return json({ items, page, page_size: size, total: applications.length });
    }
    if (method === "POST" && path === "/applications") {
      const status = byKey(String(body.initial_status ?? "to_prepare"));
      const now = new Date().toISOString();
      const offer = offers.find((o) => o.id === body.offer_id);
      if (body.offer_id && !offer) return error(404, "not_found", "Offre introuvable");
      const created: Application = {
        id: `application-${nextId++}`,
        offer_id: offer?.id ?? null,
        company: offer?.company ?? String(body.company),
        title: offer?.title ?? String(body.title),
        status,
        notes: (body.notes as string | undefined) ?? null,
        sent_at: null,
        created_at: now,
        updated_at: now,
      };
      applications.unshift(created);
      record(created, null, status.name, "Candidature créée");
      return json(created, 201);
    }

    const match = /^\/applications\/([^/]+)(\/status|\/confirm-sent|\/events)?$/.exec(path);
    const application = match ? applications.find((a) => a.id === match[1]) : undefined;
    if (!match || !application) return error(404, "not_found", "Candidature introuvable");

    if (method === "GET" && match[2] === "/events") {
      const items = events.get(application.id) ?? [];
      return json({ items, page: 1, page_size: 25, total: items.length });
    }
    if (method === "POST" && match[2] === "/status") {
      const target = statuses.find((s) => s.id === body.status_id);
      if (!target) return error(404, "not_found", "Statut introuvable");
      if (target.system_key === "sent") {
        return error(409, "confirmation_required", "Utiliser la confirmation d'envoi pour passer à « Envoyée »");
      }
      record(application, application.status.name, target.name, (body.comment as string | undefined) ?? null);
      application.status = target;
      return json(application);
    }
    if (method === "POST" && match[2] === "/confirm-sent") {
      if (body.confirmed !== true) return error(409, "confirmation_required", "Confirmation explicite requise");
      if (application.status.system_key === "sent") return error(409, "already_sent", "Déjà marquée comme envoyée");
      record(application, application.status.name, "Envoyée", "Envoi confirmé par l'utilisateur");
      application.status = byKey("sent");
      application.sent_at = new Date().toISOString();
      return json(application);
    }
    return error(404, "not_found", "Route inconnue");
  };
}

