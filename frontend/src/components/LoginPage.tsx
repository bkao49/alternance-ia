import { useState, type FormEvent } from "react";

import { ApiFailure } from "../api/client";

type Props = { onLogin: (email: string, password: string) => Promise<void>; demo: boolean };

export function LoginPage({ onLogin, demo }: Props) {
  const [email, setEmail] = useState(demo ? "demo@example.test" : "");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onLogin(email, password);
    } catch (failure) {
      setError(
        failure instanceof ApiFailure && failure.status === 429
          ? "Trop de tentatives. Réessayez dans quelques minutes."
          : "Identifiants invalides.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <form className="card login-card" onSubmit={submit}>
        <h1>Suivi d'alternance</h1>
        <p className="muted">Connectez-vous pour retrouver vos candidatures.</p>
        {demo && (
          <p className="notice" role="note">
            Mode démonstration : données fictives, mot de passe <code>demo-demo</code>.
          </p>
        )}
        <label>
          Adresse e-mail
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label>
          Mot de passe
          <input
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <button type="submit" className="primary" disabled={busy}>
          {busy ? "Connexion…" : "Se connecter"}
        </button>
      </form>
    </main>
  );
}
