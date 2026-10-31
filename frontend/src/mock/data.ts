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

type Detail = [Offer["contract_type"], string, string];
const DETAILS: Record<string, Detail> = {
  "Globex IA": ["apprenticeship", "Paris", "Vos projets de classification et Python correspondent aux compétences demandées."],
  "Initech Data": ["apprenticeship", "Lyon", "SQL, Docker et PostgreSQL sont dans votre profil. Airflow manque."],
  "Acme Analytics": ["internship", "Nantes", "Mission centrée sur les tableaux de bord déjà réalisés dans vos projets."],
  "Stark Mobilité": ["fixed_term", "Toulouse", "Déploiement de modèles avec Docker, comme dans l'un de vos projets."],
  "Hooli Labs": ["apprenticeship", "Paris", "Bonne correspondance sur Python ; l'IA générative n'est pas dans votre profil."],
};

// Offres fictives sans candidature : on peut en préparer une depuis l'écran des offres.
const EXTRA_OFFERS: [string, string, Detail, number][] = [
  ["Nimbus Cloud", "Data Engineer", ["permanent", "Lyon", "SQL et Docker correspondent ; la partie cloud est nouvelle pour vous."], 4.3],
  ["Orion Analytics", "Stagiaire Data Scientist", ["internship", "Paris", "Statistiques et Python sont dans votre profil."], 4.0],
  ["Vega Logistique", "Data Analyst", ["fixed_term", "Nantes", "Tableaux de bord et SQL demandés, comme dans vos projets."], 3.7],
  ["Atlas Conseil", "Ingénieur IA", ["permanent", "Toulouse", "Le niveau d'expérience demandé dépasse un peu votre profil."], 3.6],
  ["Helios Énergie", "Alternant Business Intelligence", ["apprenticeship", "Lille", "Outils de BI et SQL correspondent à votre formation."], 3.5],
  ["Borea Média", "Data Analyst", ["permanent", "Bordeaux", "Peu de recoupements avec vos critères."], 2.8],
];

export function seedOffers(applications: Application[]): Offer[] {
  const linked = applications
    .filter((a) => a.offer_id)
    .map((a): Offer => {
      const [contract_type, location, explanation] = DETAILS[a.company ?? ""] as Detail;
      return {
        id: a.offer_id as string,
        title: a.title ?? "",
        company: a.company ?? "",
        location,
        source: "source_fictive",
        url: "https://example.test/offre",
        detected_at: a.created_at,
        expired: false,
        contract_type,
        score: OFFER_SCORES[a.company ?? ""],
        explanation,
      };
    });
  const extra = EXTRA_OFFERS.map(([company, title, [contract_type, location, explanation], score], index): Offer => ({
    id: `offer-extra-${index + 1}`,
    title,
    company,
    location,
    source: "source_fictive",
    url: "https://example.test/offre",
    detected_at: "2026-10-28T08:00:00Z",
    expired: false,
    contract_type,
    score,
    explanation,
  }));
  return [...linked, ...extra].sort((a, b) => (b.score ?? 0) - (a.score ?? 0));
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
