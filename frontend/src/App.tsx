import { Dashboard } from "./components/Dashboard";
import { LoginPage } from "./components/LoginPage";
import { useSession } from "./hooks";
import { DEMO } from "./mock/demoInfo";

export default function App() {
  const { user, login, logout } = useSession();

  if (user === undefined) return <p role="status" className="boot">Chargement…</p>;
  if (user === null) return <LoginPage onLogin={login} demo={import.meta.env.MODE === "mock" ? DEMO : undefined} />;
  return <Dashboard user={user} onLogout={logout} />;
}
