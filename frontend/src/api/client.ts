import createClient, { type Middleware } from "openapi-fetch";

import { mockFetch } from "../mock/mockFetch";
import type { paths } from "./schema";

export class ApiFailure extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export function readCookie(name: string): string | undefined {
  return document.cookie
    .split("; ")
    .find((part) => part.startsWith(`${name}=`))
    ?.slice(name.length + 1);
}

// Double soumission CSRF : le cookie lisible `csrf_token` est renvoyé en en-tête pour toute écriture.
export const csrfMiddleware: Middleware = {
  onRequest({ request }) {
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method)) {
      const token = readCookie("csrf_token");
      if (token) request.headers.set("X-CSRF-Token", token);
    }
    return request;
  },
};

export function createApi(fetchImpl?: (request: Request) => Promise<Response>) {
  const client = createClient<paths>({ baseUrl: `${window.location.origin}/api`, fetch: fetchImpl });
  client.use(csrfMiddleware);
  return client;
}

export type Api = ReturnType<typeof createApi>;

// `npm run dev:mock` : l'interface tourne avec des données fictives, sans backend.
export const api: Api = createApi(import.meta.env.MODE === "mock" ? mockFetch : undefined);

type Result<T> = { data?: T; error?: unknown; response: Response };

export function unwrap<T>(result: Result<T>): T {
  if (result.error !== undefined || result.data === undefined) {
    const body = result.error as { code?: string; message?: string } | undefined;
    throw new ApiFailure(result.response.status, body?.code ?? "error", body?.message ?? "Erreur inattendue");
  }
  return result.data;
}
