import { useEffect, useState, type FormEvent } from "react";

import { unwrap } from "../api/client";
import { useApi } from "../api/context";
import type { Mailbox } from "../api/types";

const when = (iso?: string) =>
  iso ? new Date(iso).toLocaleString("fr-FR", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "";

/** Boîte e-mail dédiée aux alertes : le mot de passe part au serveur et n'est jamais relu ni réaffiché. */
export function EmailBoxEditor({ onChanged }: { onChanged: () => void }) {
  const api = useApi();
  const [box, setBox] = useState<Mailbox | null>(null);
  const [host, setHost] = useState("");
  const [username, setUsername] = useState("");
  const [folder, setFolder] = useState("INBOX");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function show(next: Mailbox) {
    setBox(next);
    setHost(next.host ?? "");
    setUsername(next.username ?? "");
    setFolder(next.folder ?? "INBOX");
    setPassword("");
  }

  useEffect(() => {
    let active = true;
    api
      .GET("/sources/email/mailbox")
      .then(unwrap)
      .then((loaded) => active && show(loaded))
      .catch((e: unknown) => active && setError(e instanceof Error ? e.message : "Chargement impossible"));
    return () => {
      active = false;
    };
  }, [api]);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    setInfo(null);
    try {
      await action();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Action impossible");
    }
    setBusy(false);
  }

  const save = (event: FormEvent) => {
    event.preventDefault();
    void run(async () => {
      const body = { host, port: 993 as const, username, folder, ...(password ? { password } : {}) };
      show(unwrap(await api.PUT("/sources/email/mailbox", { body })));
      setInfo("Boîte enregistrée. Testez la connexion avant d'activer la source.");
      onChanged();
    });
  };
  const test = () =>
    void run(async () => {
      const result = unwrap(await api.POST("/sources/email/mailbox/test"));
      setInfo(result.message);
      show(unwrap(await api.GET("/sources/email/mailbox")));
    });
  const remove = () =>
    void run(async () => {
      const result = await api.DELETE("/sources/email/mailbox");
      if (!result.response.ok) throw new Error("Suppression impossible");
      show({ configured: false });
      setInfo("Boîte supprimée.");
      onChanged();
    });

  if (!box) return error ? <p role="alert" className="error">{error}</p> : <p role="status">Chargement…</p>;
  return (
    <div className="mailbox">
      <details className="guide">
        <summary>Comment brancher mes alertes, pas à pas</summary>
        <ol>
          <li>
            <strong>Créez une boîte e-mail réservée aux alertes</strong> (une nouvelle adresse chez Gmail, Outlook…). N'utilisez jamais votre
            boîte personnelle : le robot y marque les messages comme lus.
          </li>
          <li>
            Dans les réglages de cette boîte, activez l'accès <strong>IMAP</strong> et créez un <strong>mot de passe d'application</strong>
            (en général après avoir activé la validation en deux étapes). Ne donnez jamais le vrai mot de passe de la boîte.
          </li>
          <li>
            <strong>Créez vous-même l'alerte emploi</strong> sur LinkedIn, Indeed, Welcome to the Jungle…, avec l'adresse de cette boîte.
            Ereuna ne se connecte jamais à votre compte LinkedIn et ne visite pas ces sites : il lit seulement les e-mails que vous
            recevez.
          </li>
          <li>Renseignez ci-dessous le serveur IMAP (par exemple imap.gmail.com), l'adresse de la boîte et le mot de passe d'application, puis testez.</li>
        </ol>
      </details>

      <form onSubmit={save} className="form" aria-busy={busy}>
        <fieldset disabled={busy} className="plain">
          <label>
            Serveur IMAP
            <input value={host} maxLength={253} placeholder="imap.exemple.fr" autoComplete="off" onChange={(e) => setHost(e.target.value)} required />
          </label>
          <label>
            Adresse de la boîte dédiée
            <input value={username} maxLength={254} autoComplete="off" onChange={(e) => setUsername(e.target.value)} required />
          </label>
          <label>
            Mot de passe d'application
            <input
              type="password"
              value={password}
              maxLength={200}
              autoComplete="new-password"
              placeholder={box.configured ? "Laisser vide pour garder celui enregistré" : ""}
              onChange={(e) => setPassword(e.target.value)}
              required={!box.configured}
            />
          </label>
          <label>
            Dossier lu
            <input value={folder} maxLength={100} onChange={(e) => setFolder(e.target.value)} required />
          </label>
          <p className="hint">Port 993 (IMAP sécurisé). Le mot de passe est chiffré sur le serveur et n'est jamais réaffiché.</p>
          <div className="actions">
            <button type="submit" className="primary">
              Enregistrer la boîte
            </button>
            {box.configured && (
              <>
                <button type="button" onClick={test}>
                  Tester la connexion
                </button>
                <button type="button" onClick={remove}>
                  Supprimer la boîte
                </button>
              </>
            )}
          </div>
        </fieldset>
      </form>
      {box.configured && box.last_test_at && (
        <p className="hint">
          Dernier test, {when(box.last_test_at)} : {box.last_test_ok ? "réussi" : (box.last_test_error ?? "échec")}.
        </p>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <p role="status" aria-live="polite">{info ?? ""}</p>
    </div>
  );
}
