import { useEffect, useState } from "react";

import { Dashboard } from "./components/Dashboard";
import { LoginPage } from "./components/LoginPage";
import type { Page } from "./components/Sidebar";
import { useSession } from "./hooks";
import { BOT_DEMO, DEMO } from "./mock/demoInfo";

const pageOf = (): Page => (window.location.hash === "#criteres" ? "criteria" : "home");

export default function App() {
  const { user, login, logout } = useSession();
  const [page, setPage] = useState<Page>(pageOf);

  useEffect(() => {
    const onHash = () => setPage(pageOf());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    // L'ancre (#candidatures) n'existe qu'après le rendu de la page : on la rejoint ici.
    const target = document.getElementById(window.location.hash.slice(1));
    // jsdom (tests) n'implémente pas scrollIntoView.
    target?.scrollIntoView?.({ behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }, [page, user]);

  if (user === undefined) return <p role="status" className="boot">Chargement…</p>;
  // Comparaison écrite en ligne : le build de production la remplace par `false` et retire la démo.
  if (user === null) return <LoginPage onLogin={login} demo={import.meta.env.MODE === "mock" ? DEMO : undefined} />;
  return <Dashboard user={user} page={page} onLogout={logout} botActivity={import.meta.env.MODE === "mock" ? BOT_DEMO : undefined} />;
}
