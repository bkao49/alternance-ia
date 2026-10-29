import { Dashboard } from "./components/Dashboard";
import { LoginPage } from "./components/LoginPage";
import { useSession } from "./hooks";
import { BOT_DEMO, DEMO } from "./mock/demoInfo";

export default function App() {
  const { user, login, logout } = useSession();

  if (user === undefined) return <p role="status" className="boot">Chargement…</p>;
  // Comparaison écrite en ligne : le build de production la remplace par `false` et retire la démo.
  if (user === null) return <LoginPage onLogin={login} demo={import.meta.env.MODE === "mock" ? DEMO : undefined} />;
  return <Dashboard user={user} onLogout={logout} botActivity={import.meta.env.MODE === "mock" ? BOT_DEMO : undefined} />;
}
