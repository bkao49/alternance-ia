import { useCallback, useEffect, useState } from "react";

import { unwrap, type Api } from "./api/client";
import { useApi } from "./api/context";
import type { Application, DashboardStats, Me, Status } from "./api/types";

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
    return () => {
      active = false;
    };
  }, [api]);

  const login = useCallback(
    async (email: string, password: string) => {
      setUser(unwrap(await api.POST("/auth/login", { body: { email, password } })));
    },
    [api],
  );
  const logout = useCallback(async () => {
    await api.POST("/auth/logout");
    setUser(null);
  }, [api]);

  return { user, login, logout };
}

export type DashboardData = { statuses: Status[]; applications: Application[]; stats: DashboardStats };
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

  try {
    const [statuses, stats, applications] = await Promise.all([
      api.GET("/statuses").then(unwrap),
      api.GET("/dashboard/stats").then(unwrap),
      loadAllApplications(),
    ]);
    return { phase: "ready", statuses, stats, applications };
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
