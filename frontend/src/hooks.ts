import { useCallback, useEffect, useState } from "react";

import type { Middleware } from "openapi-fetch";

import { ApiFailure, unwrap, type Api } from "./api/client";
import { useApi } from "./api/context";
import type { Application, DashboardStats, Me, Offer, Status } from "./api/types";

export type SessionState = { user: Me | null | undefined; login: (email: string, password: string) => Promise<void>; logout: () => Promise<void> };

/** `user` vaut `undefined` pendant la vérification de la session, `null` si non connecté. */
export function useSession(): SessionState {
  const api = useApi();
  const [user, setUser] = useState<Me | null | undefined>(undefined);

  useEffect(() => {
    let active = true;
    api
      .GET("/auth/me")
      .then((result) => active && setUser(result.data ?? null))
      .catch(() => active && setUser(null));

    // Session expirée en cours d'usage : n'importe quelle réponse 401 ramène à l'écran de connexion.
    const onExpiredSession: Middleware = {
      onResponse({ request, response }) {
        const path = new URL(request.url).pathname;
        if (response.status === 401 && !path.endsWith("/auth/login") && !path.endsWith("/auth/me")) setUser(null);
      },
    };
    api.use(onExpiredSession);
    return () => {
      active = false;
      api.eject(onExpiredSession);
    };
  }, [api]);

  const login = useCallback(
    async (email: string, password: string) => {
      setUser(unwrap(await api.POST("/auth/login", { body: { email, password } })));
    },
    [api],
  );
  const logout = useCallback(async () => {
    const result = await api.POST("/auth/logout");
    // 401 : la session n'existait déjà plus. Toute autre erreur : on ne prétend pas être déconnecté.
    if (result.error !== undefined && result.response.status !== 401) {
      throw new ApiFailure(result.response.status, "logout_failed", "Déconnexion impossible, réessayez.");
    }
    setUser(null);
  }, [api]);

  return { user, login, logout };
}

/** Score de chaque offre qui en a un, par identifiant d'offre : une candidature liée à une offre en hérite. */
export type ScoresByOffer = Record<string, number>;

export type DashboardData = { statuses: Status[]; applications: Application[]; stats: DashboardStats; scores: ScoresByOffer };
export type DashboardState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | ({ phase: "ready" } & DashboardData);

const PAGE_SIZE = 100;

async function fetchDashboard(api: Api): Promise<DashboardState> {
  async function loadAllApplications(): Promise<Application[]> {
    const items: Application[] = [];
    for (let page = 1; ; page += 1) {
      const result = unwrap(await api.GET("/applications", { params: { query: { page, page_size: PAGE_SIZE } } }));
      items.push(...result.items);
      if (items.length >= result.total || result.items.length === 0) return items;
    }
  }

  async function loadScores(): Promise<ScoresByOffer> {
    const scores: ScoresByOffer = {};
    try {
      let seen = 0;
      for (let page = 1; ; page += 1) {
        const result = unwrap(await api.GET("/offers", { params: { query: { page, page_size: PAGE_SIZE } } }));
        for (const offer of result.items as Offer[]) if (offer.score !== undefined) scores[offer.id] = offer.score;
        seen += result.items.length;
        if (seen >= result.total || result.items.length === 0) break;
      }
    } catch {
      // Les scores sont un plus : sans eux, la colonne affiche des tirets et le reste de l'écran fonctionne.
    }
    return scores;
  }

  try {
    const [statuses, stats, applications, scores] = await Promise.all([
      api.GET("/statuses").then(unwrap),
      api.GET("/dashboard/stats").then(unwrap),
      loadAllApplications(),
      loadScores(),
    ]);
    return { phase: "ready", statuses, stats, applications, scores };
  } catch (error) {
    return { phase: "error", message: error instanceof Error ? error.message : "Chargement impossible" };
  }
}

export function useDashboardData(): { state: DashboardState; reload: () => Promise<void> } {
  const api = useApi();
  const [state, setState] = useState<DashboardState>({ phase: "loading" });

  useEffect(() => {
    let active = true;
    void fetchDashboard(api).then((next) => active && setState(next));
    return () => {
      active = false;
    };
  }, [api]);

  const reload = useCallback(async () => setState(await fetchDashboard(api)), [api]);

  return { state, reload };
}
