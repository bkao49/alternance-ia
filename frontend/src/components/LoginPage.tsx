import { useState, type FormEvent } from "react";

import { ApiFailure } from "../api/client";
import { APP_NAME } from "../brand";
import { Logo } from "./Logo";

type Props = {
  onLogin: (email: string, password: string) => Promise<void>;
  demo?: { email: string; password: string };
};

function messageFor(failure: unknown): string {
  if (failure instanceof ApiFailure) {
    if (failure.status === 401) return "Identifiants invalides.";
    if (failure.status === 429) return "Trop de tentatives. Réessayez dans quelques minutes.";
    if (failure.status === 422) return "Adresse e-mail ou mot de passe invalide.";
  }
  return "Connexion impossible pour le moment. Réessayez dans un instant.";
}

export function LoginPage({ onLogin, demo }: Props) {
  const [email, setEmail] = useState(demo?.email ?? "");
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
      setError(messageFor(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <form className="card login-card" onSubmit={submit}>
        <h1 className="brand">
          <Logo className="brand-logo" />
          <span className="brand-name">{APP_NAME}</span>
        </h1>
        <p className="muted">Connectez-vous pour retrouver vos offres et vos candidatures.</p>
        {demo && (
          <p className="notice" role="note">
            Mode démonstration : données fictives, mot de passe <code>{demo.password}</code>.
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
