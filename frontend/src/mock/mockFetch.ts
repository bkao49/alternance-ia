import type { Application, ApplicationEvent, DashboardStats, ProfileCv, ProfileFact, SearchPreferences, Status } from "../api/types";
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
export function createMockFetch() {
  const statuses: Status[] = seedStatuses();
  const applications: Application[] = seedApplications(statuses);
  const offers = seedOffers(applications);
  const events = new Map<string, ApplicationEvent[]>();
  let signedIn = false;
  let facts: ProfileFact[] = [];
  let cv: { info: ProfileCv; readyAt: number } | null = null;
  let preferences: SearchPreferences = {
    keywords: [], locations: [], remote_accepted: false, contract_types: [], start_date: null,
    duration_months: null, alternance_rhythm: null, education_level: null, min_salary_eur: null,
    excluded_keywords: [], updated_at: null,
  };
  let nextId = applications.length + 1;

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
        relevant: 14,
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
    if (method === "PUT" && path === "/preferences") {
      preferences = { ...(body as Omit<SearchPreferences, "updated_at">), updated_at: new Date().toISOString() };
      return json(preferences);
    }

    if (method === "GET" && path === "/offers") {
      const page = Number(url.searchParams.get("page") ?? 1);
      const size = Number(url.searchParams.get("page_size") ?? 25);
      return json({ items: offers.slice((page - 1) * size, page * size), page, page_size: size, total: offers.length });
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
      const created: Application = {
        id: `application-${nextId++}`,
        offer_id: null,
        company: String(body.company),
        title: String(body.title),
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

