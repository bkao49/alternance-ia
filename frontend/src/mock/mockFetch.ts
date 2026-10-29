import type { Application, ApplicationEvent, DashboardStats, Status } from "../api/types";
import { seedApplications, seedStatuses } from "./data";

export const DEMO_PASSWORD = "demo-demo";
const DEMO_USER = { id: "user-demo", email: "demo@example.test" };
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
  const events = new Map<string, ApplicationEvent[]>();
  let signedIn = false;
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
    const hasBody = method === "POST" || method === "PATCH";
    const body = hasBody ? ((await request.json().catch(() => ({}))) as Record<string, unknown>) : {};

    if (method === "POST" && path === "/auth/login") {
      if (body.password !== DEMO_PASSWORD) return error(401, "invalid_credentials", "Identifiants invalides");
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

export const mockFetch = createMockFetch();
