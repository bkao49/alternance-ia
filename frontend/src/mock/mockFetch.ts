import type { Application, ApplicationEvent, DashboardStats, ProfileFact, SearchPreferences, Status } from "../api/types";
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
  let preferences: SearchPreferences = {
    keywords: [], locations: [], remote_accepted: false, contract_types: [], start_date: null,
    duration_months: null, alternance_rhythm: null, education_level: null, min_salary_eur: null,
    excluded_keywords: [], updated_at: null,
  };
  let nextId = applications.length + 1;

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
    const hasBody = method === "POST" || method === "PATCH" || method === "PUT";
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
    if (factMatch) {
      const id = factMatch[1];
      if (!id && method === "GET") return json(facts);
      if (!id && method === "POST") {
        const created = { ...(body as Omit<ProfileFact, "id" | "created_at">), id: `fact-${nextId++}`, created_at: new Date().toISOString() };
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

