import { useEffect, useState } from "react";

import type { BotStatus } from "../api/types";

const VISIBLE = 3;
const time = (date: Date | string) =>
  new Date(date).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });

function NextRun({ at }: { at: Date }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);

  const left = Math.max(0, Math.round((at.getTime() - now) / 60_000));
  return (
    <div className="bot-next">
      <div className="bot-next-time num">{time(at)}</div>
      <div>
        prochaine collecte, <span className="num">dans {Math.floor(left / 60)} h {String(left % 60).padStart(2, "0")} min</span>
      </div>
    </div>
  );
}

/** Bloc « Le bot » de l'accueil, alimenté par GET /bot/status. Sans collecte, il le dit et n'invente rien. */
export function BotPanel({ status }: { status?: BotStatus }) {
  const activity = status?.activity.slice(0, VISIBLE) ?? [];
  // Les sources en échec ou bloquées sont signalées ; une source simplement non activée n'est pas un problème.
  const problems = status?.sources.filter((s) => s.state === "blocked" || s.state === "error") ?? [];
  const working = activity.length > 0;
  const next = status?.next_run_at ? new Date(status.next_run_at) : undefined;

  return (
    <section className="bot" aria-labelledby="bot-title">
      <header className="bot-header">
        <h2 id="bot-title">{working ? "Le bot travaille" : "Le bot"}</h2>
        {next && (
          <span className="bot-live">
            <i aria-hidden="true" />
            Actif
          </span>
        )}
      </header>
      {working ? (
        <>
          <ul className="bot-feed" aria-label="Dernières actions du bot">
            {activity.map((line) => (
              <li key={`${line.at}-${line.source}`}>
                <time dateTime={line.at}>{time(line.at)}</time>
                {line.source} : {line.message}
              </li>
            ))}
          </ul>
          {next && <NextRun at={next} />}
        </>
      ) : (
        <div className="bot-empty">
          <p className="bot-empty-title">Aucune collecte pour l'instant.</p>
          <p>Les offres trouvées par le bot apparaîtront ici dès que les sources seront branchées.</p>
        </div>
      )}
      {problems.length > 0 && (
        <ul className="bot-problems" aria-label="Sources à surveiller">
          {problems.map((s) => (
            <li key={s.source}>
              {s.source} : {s.state === "blocked" ? "bloquée" : "en échec"}, {s.cause}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
