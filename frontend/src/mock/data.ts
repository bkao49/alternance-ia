import type { Application, Offer, Status } from "../api/types";

// Données entièrement fictives (entreprises et postes inventés) pour la démonstration et les tests.
const DEFAULTS: [string, string, string][] = [
  ["detected", "Détectée", "#64748b"],
  ["analyzed", "Analysée", "#0ea5e9"],
  ["to_prepare", "À préparer", "#f59e0b"],
  ["human_review", "À valider par un humain", "#8b5cf6"],
  ["sent", "Envoyée", "#4f46e5"],
  ["waiting", "En attente", "#94a3b8"],
  ["interview", "Entretien", "#10b981"],
  ["rejected", "Refusée", "#ef4444"],
  ["offer_received", "Offre reçue", "#22c55e"],
  ["abandoned", "Abandonnée", "#6b7280"],
];

export function seedStatuses(): Status[] {
  return DEFAULTS.map(([key, name, color], index) => ({
    id: `status-${key}`,
    name,
    color,
    position: index + 1,
    system_key: key as Status["system_key"],
  }));
}

const SENT_KEYS = ["sent", "waiting", "interview", "rejected", "offer_received"];

const SAMPLES: [string, string, string, string][] = [
  ["Acme Analytics", "Alternant Data Analyst", "analyzed", "2026-10-20"],
  ["Globex IA", "Alternant Machine Learning", "to_prepare", "2026-10-22"],
  ["Initech Data", "Alternant Data Engineer", "human_review", "2026-10-23"],
  ["Hooli Labs", "Alternant IA générative", "sent", "2026-10-12"],
  ["Umbrella Santé", "Alternant Data Scientist", "waiting", "2026-10-09"],
  ["Stark Mobilité", "Alternant MLOps", "interview", "2026-10-02"],
  ["Wayne Énergie", "Alternant Analytics Engineer", "rejected", "2026-09-28"],
  ["Cyberdyne Vision", "Alternant Computer Vision", "detected", "2026-10-27"],
  ["Soylent Foods", "Alternant Business Intelligence", "detected", "2026-10-26"],
  ["Tyrell Robotique", "Alternant Data Engineer", "offer_received", "2026-09-18"],
  ["Pied Piper", "Alternant Data Platform", "abandoned", "2026-09-30"],
  ["Massive Dynamic", "Alternant Recherche IA", "to_prepare", "2026-10-25"],
];

// Offres fictives (avec score) auxquelles certaines candidatures sont rattachées ; les autres sont saisies à la main.
const OFFER_SCORES: Record<string, number> = {
  "Globex IA": 4.6,
  "Initech Data": 4.4,
  "Acme Analytics": 4.2,
  "Stark Mobilité": 4.1,
  "Hooli Labs": 3.9,
};

export function seedOffers(applications: Application[]): Offer[] {
  return applications
    .filter((a) => a.offer_id)
    .map((a) => ({
      id: a.offer_id as string,
      title: a.title ?? "",
      company: a.company ?? "",
      source: "source_fictive",
      url: "https://example.test/offre",
      detected_at: a.created_at,
      expired: false,
      score: OFFER_SCORES[a.company ?? ""],
    }));
}

export function seedApplications(statuses: Status[]): Application[] {
  return SAMPLES.map(([company, title, key, day], index) => {
    const status = statuses.find((s) => s.system_key === key) as Status;
    const created = `${day}T09:00:00Z`;
    return {
      id: `application-${index + 1}`,
      offer_id: company in OFFER_SCORES ? `offer-${index + 1}` : null,
      company,
      title,
      status,
      notes: null,
      sent_at: SENT_KEYS.includes(key) ? created : null,
      created_at: created,
      updated_at: created,
    };
  });
}
