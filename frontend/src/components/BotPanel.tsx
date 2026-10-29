import { useEffect, useState } from "react";

/** Activité du bot. Fournie seulement en mode démonstration tant que l'API n'expose pas les collectes. */
export type BotActivity = { minutesToNext: number; steps: readonly (readonly [string, string])[] };

const VISIBLE = 3;
const STEP_MS = 1800;
const PAUSE_MS = 5000;
const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

function useFeed(steps: BotActivity["steps"]) {
  const [shown, setShown] = useState(() => (reducedMotion() ? steps.length : 1));

  useEffect(() => {
    if (reducedMotion()) return;
    const timer = setTimeout(() => setShown((n) => (n >= steps.length ? 1 : n + 1)), shown >= steps.length ? PAUSE_MS : STEP_MS);
    return () => clearTimeout(timer);
  }, [shown, steps.length]);

  return steps.slice(0, shown).slice(-VISIBLE);
}

function NextRun({ minutesToNext }: { minutesToNext: number }) {
  const [at] = useState(() => new Date(Date.now() + minutesToNext * 60_000));
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);

  const left = Math.max(0, Math.round((at.getTime() - now) / 60_000));
  const time = at.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  return (
    <div className="bot-next">
      <div className="bot-next-time num">{time}</div>
      <div>
        prochaine collecte, <span className="num">dans {Math.floor(left / 60)} h {String(left % 60).padStart(2, "0")} min</span>
      </div>
    </div>
  );
}

function Feed({ steps }: { steps: BotActivity["steps"] }) {
  const lines = useFeed(steps);
  return (
    <ul className="bot-feed" aria-label="Dernières actions du bot">
      {lines.map(([time, text]) => (
        <li key={`${time}-${text}`}>
          <time>{time}</time>
          {text}
        </li>
      ))}
    </ul>
  );
}

export function BotPanel({ activity }: { activity?: BotActivity }) {
  return (
    <section className="bot" aria-labelledby="bot-title">
      <header className="bot-header">
        <h2 id="bot-title">{activity ? "Le bot travaille" : "Le bot"}</h2>
        {activity && (
          <span className="bot-live">
            <i aria-hidden="true" />
            En cours
          </span>
        )}
      </header>
      {activity ? (
        <>
          <Feed steps={activity.steps} />
          <NextRun minutesToNext={activity.minutesToNext} />
        </>
      ) : (
        <div className="bot-empty">
          <p className="bot-empty-title">Aucune collecte pour l'instant.</p>
          <p>Les offres trouvées par le bot apparaîtront ici dès que les sources seront branchées.</p>
        </div>
      )}
    </section>
  );
}
