import { beforeEach, describe, expect, it } from "vitest";

import { ApiFailure, createApi, readCookie, unwrap } from "./client";

function recordingFetch() {
  const seen: Request[] = [];
  const fetchImpl = async (request: Request) => {
    seen.push(request);
    return new Response(JSON.stringify([]), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  return { seen, fetchImpl };
}

beforeEach(() => {
  document.cookie = "csrf_token=abc123; path=/";
});

describe("jeton CSRF", () => {
  it("est lu depuis le cookie", () => {
    expect(readCookie("csrf_token")).toBe("abc123");
    expect(readCookie("absent")).toBeUndefined();
  });

  it("est envoyé en en-tête sur les écritures seulement", async () => {
    const { seen, fetchImpl } = recordingFetch();
    const api = createApi(fetchImpl);
    await api.GET("/statuses");
    await api.POST("/statuses", { body: { name: "Relance" } });
    expect(seen[0]?.headers.get("X-CSRF-Token")).toBeNull();
    expect(seen[1]?.headers.get("X-CSRF-Token")).toBe("abc123");
  });
});

describe("unwrap", () => {
  it("renvoie les données, ou lève l'erreur du contrat", () => {
    expect(unwrap({ data: [1], response: new Response() })).toEqual([1]);
    const failure = () =>
      unwrap({ error: { code: "confirmation_required", message: "Confirmation requise" }, response: new Response(null, { status: 409 }) });
    expect(failure).toThrow(ApiFailure);
    expect(failure).toThrow("Confirmation requise");
  });
});
