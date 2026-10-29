import { Dashboard } from "./components/Dashboard";
import { LoginPage } from "./components/LoginPage";
import { useSession } from "./hooks";

export default function App() {
  const { user, login, logout } = useSession();

  if (user === undefined) return <p role="status" className="boot">Chargement…</p>;
  if (user === null) return <LoginPage onLogin={login} demo={import.meta.env.MODE === "mock"} />;
  return <Dashboard user={user} onLogout={() => void logout()} />;
}
