import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { createApi } from "../api/client";
import { ApiContext } from "../api/context";
import App from "../App";
import { createMockFetch } from "../mock/mockFetch";
import { DEMO } from "../mock/demoInfo";

export type User = ReturnType<typeof userEvent.setup>;

/** Permet à un test de remplacer la réponse du faux backend pour certaines requêtes. */
export type Intercept = (request: Request) => Response | undefined;

/** Requêtes envoyées par l'application depuis le dernier `renderApp`. */
export let requests: Request[] = [];

export const failure = (status: number, code: string, message: string) =>
  new Response(JSON.stringify({ code, message }), { status, headers: { "Content-Type": "application/json" } });

export function renderApp(intercept?: Intercept): User {
  const mock = createMockFetch();
  requests = [];
  const api = createApi(async (request) => {
    requests.push(request.clone());
    return intercept?.(request) ?? mock(request);
  });
  render(
    <ApiContext.Provider value={api}>
      <App />
    </ApiContext.Provider>,
  );
  return userEvent.setup();
}

export async function signIn(user: User, password: string = DEMO.password) {
  await user.type(await screen.findByLabelText("Adresse e-mail"), DEMO.email);
  await user.type(screen.getByLabelText("Mot de passe"), password);
  await user.click(screen.getByRole("button", { name: "Se connecter" }));
}

export async function signedInApp(intercept?: Intercept): Promise<User> {
  const user = renderApp(intercept);
  await signIn(user);
  await screen.findByRole("heading", { name: "Candidatures" });
  return user;
}

export const bodyRows = () => within(screen.getByRole("table")).getAllByRole("row").slice(1);
export const firstCompany = () => within(bodyRows()[0] as HTMLElement).getAllByRole("rowheader")[0]?.textContent;
export const counter = (label: string) =>
  within(screen.getByRole("region", { name: "Chiffres clés" })).getByText(label).parentElement;

export const validateMove = (name: string) => screen.getByRole("button", { name: `Valider le déplacement de ${name}` });
