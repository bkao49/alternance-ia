"""Contrôle de l'installation : `python -m app.doctor` (ou `docker compose run --rm doctor`).

Vérifie la base, les migrations, les clés renseignées (oui ou non, jamais la valeur) et qu'un appel de
test à chaque source configurée répond. Chaque manque est expliqué en français. Code de sortie 1 s'il
reste un problème bloquant. Aucune donnée personnelle, aucun secret dans la sortie.
"""
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from app.ai.gateway.claude import check_api_key
from app.collectors.adzuna import AdzunaCollector
from app.collectors.base import Collector, CollectorError, SearchQuery
from app.collectors.france_travail import FranceTravailCollector, NotSubscribed
from app.collectors.lba import LbaCollector
from app.collectors.mail import ImapMailClient

BACKEND = Path(__file__).resolve().parent.parent
OK, TODO, ERROR = "[OK]", "[A FAIRE]", "[ERREUR]"
Probe = Callable[[], "str | Line | None"]  # None : la source répond ; sinon une phrase (ERREUR) ou une Line


@dataclass(frozen=True)
class Line:
    level: str
    message: str


def _set(env: dict[str, str], *names: str) -> bool:
    return all(env.get(name, "").strip() for name in names)


def check_database(env: dict[str, str]) -> list[Line]:
    url = env.get("MIGRATION_DATABASE_URL") or env.get("DATABASE_URL")
    if not url:
        return [Line(ERROR, "Base : DATABASE_URL n'est pas défini. Lancez la commande avec "
                            "« docker compose run --rm doctor » après avoir rempli .env.")]
    engine = create_engine(url.replace("postgresql://", "postgresql+psycopg://", 1))
    try:
        with engine.connect() as conn:
            current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except Exception as exc:  # noqa: BLE001 (le message du pilote peut citer l'adresse ou le mot de passe)
        return [Line(ERROR, f"Base : ne répond pas, ou migrations jamais appliquées ({type(exc).__name__}). "
                            "Démarrez-la : docker compose up -d --build.")]
    finally:
        engine.dispose()
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    lines = [Line(OK, "Base : répond.")]
    if current == head:
        return [*lines, Line(OK, f"Migrations : à jour ({head}).")]
    return [*lines, Line(ERROR, f"Migrations : base en {current}, attendu {head}. "
                                "Appliquez-les : docker compose run --rm migrate.")]


def check_keys(env: dict[str, str]) -> list[Line]:
    """Présence des clés seulement : jamais leur valeur, ni même sa longueur."""
    rows = [
        ("SECRET_KEY (32 caractères au moins)", len(env.get("SECRET_KEY", "")) >= 32, ERROR,
         "générez-la, voir le README."),
        ("ANTHROPIC_API_KEY", _set(env, "ANTHROPIC_API_KEY"), TODO,
         "sans elle, ni extraction, ni score complet, ni CV : console.anthropic.com."),
        ("ADZUNA_APP_ID et ADZUNA_APP_KEY", _set(env, "ADZUNA_APP_ID", "ADZUNA_APP_KEY"), TODO,
         "source Adzuna inactive : developer.adzuna.com."),
        ("FRANCE_TRAVAIL_CLIENT_ID et FRANCE_TRAVAIL_CLIENT_SECRET",
         _set(env, "FRANCE_TRAVAIL_CLIENT_ID", "FRANCE_TRAVAIL_CLIENT_SECRET"), TODO,
         "source France Travail inactive : francetravail.io."),
        ("LBA_API_TOKEN (La Bonne Alternance)", _set(env, "LBA_API_TOKEN"), TODO,
         "source La Bonne Alternance inactive : francetravail.io."),
        ("EMAIL_ALERTS_HOST, USER et PASSWORD",
         _set(env, "EMAIL_ALERTS_HOST", "EMAIL_ALERTS_USER", "EMAIL_ALERTS_PASSWORD"), TODO,
         "alertes e-mail inactives (facultatif)."),
    ]
    lines = [Line(OK, f"Clé {name} : renseignée.") if present else Line(level, f"Clé {name} : absente, {why}")
             for name, present, level, why in rows]
    provider = env.get("LLM_PROVIDER", "").strip().lower()
    if provider not in ("", "anthropic"):
        lines.append(Line(ERROR, "LLM_PROVIDER : seule la valeur « anthropic » est acceptée."))
    elif not provider:
        lines.append(Line(TODO, "LLM_PROVIDER : vide, l'IA est désactivée. Mettez LLM_PROVIDER=anthropic."))
    return lines


def _collector_probe(make: Callable[[], Collector]) -> Probe:
    def probe() -> str | None:
        with make() as collector:  # type: ignore[attr-defined]
            result = collector.collect(SearchQuery(keywords=("data",), max_results=1))
        return None if result.error is None else result.error.message
    return probe


def _france_travail_probe() -> Line | None:
    """Jeton puis une recherche d'une seule offre : valide le scope et l'abonnement à l'API."""
    name = "France Travail"
    try:
        with FranceTravailCollector() as collector:
            total = collector.check()
    except NotSubscribed:
        return Line(TODO, f"{name} : votre application francetravail.io n'est pas abonnée à l'API "
                          "Offres d'emploi v2, ou le scope est différent. Vérifiez l'abonnement "
                          "dans votre espace francetravail.io.")
    except CollectorError as exc:
        return Line(ERROR, f"{name} : {exc.message}")
    return Line(OK, f"{name} : l'appel de test répond ({total} offres au total).")


def _imap_probe(env: dict[str, str]) -> Probe:
    def probe() -> str | None:
        try:
            client = ImapMailClient(env["EMAIL_ALERTS_HOST"], env["EMAIL_ALERTS_USER"],
                                    env["EMAIL_ALERTS_PASSWORD"], int(env.get("EMAIL_ALERTS_PORT") or 993),
                                    env.get("EMAIL_ALERTS_FOLDER") or "INBOX")
        except Exception as exc:  # noqa: BLE001
            return getattr(exc, "message", "connexion à la boîte impossible")
        client.close()  # connexion et dossier seulement : aucun e-mail lu ni marqué
        return None
    return probe


def default_probes(env: dict[str, str]) -> dict[str, Probe]:
    probes: dict[str, Probe] = {}
    if _set(env, "ANTHROPIC_API_KEY"):
        probes["Claude (Anthropic)"] = lambda: check_api_key(env["ANTHROPIC_API_KEY"].strip())
    if _set(env, "ADZUNA_APP_ID", "ADZUNA_APP_KEY"):
        probes["Adzuna"] = _collector_probe(AdzunaCollector)
    if _set(env, "FRANCE_TRAVAIL_CLIENT_ID", "FRANCE_TRAVAIL_CLIENT_SECRET"):
        probes["France Travail"] = _france_travail_probe
    if _set(env, "LBA_API_TOKEN"):
        probes["La Bonne Alternance"] = _collector_probe(LbaCollector)
    if _set(env, "EMAIL_ALERTS_HOST", "EMAIL_ALERTS_USER", "EMAIL_ALERTS_PASSWORD"):
        probes["Alertes e-mail"] = _imap_probe(env)
    return probes


def check_sources(probes: dict[str, Probe]) -> list[Line]:
    if not probes:
        return [Line(TODO, "Sources : aucune clé renseignée, donc aucun appel de test. Voir le README.")]
    lines = []
    for name, probe in probes.items():
        try:
            problem = probe()
        except Exception as exc:  # noqa: BLE001 (le détail pourrait contenir une clé)
            problem = f"échec inattendu ({type(exc).__name__})"
        if isinstance(problem, Line):
            lines.append(problem)
        else:
            lines.append(Line(OK, f"{name} : l'appel de test répond.") if problem is None
                         else Line(ERROR, f"{name} : {problem}"))
    return lines


def run(env: dict[str, str] | None = None, probes: dict[str, Probe] | None = None) -> list[Line]:
    env = dict(os.environ if env is None else env)
    return [*check_database(env), *check_keys(env),
            *check_sources(default_probes(env) if probes is None else probes)]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    lines = run()
    for line in lines:
        print(f"{line.level} {line.message}")
    blocking = sum(line.level == ERROR for line in lines)
    todo = sum(line.level == TODO for line in lines)
    print()
    if blocking:
        print(f"{blocking} problème(s) à corriger avant de lancer l'application.")
    elif todo:
        print(f"L'application peut démarrer ; {todo} point(s) à compléter pour avoir de vraies offres.")
    else:
        print("Tout est prêt : base, migrations, clés et sources répondent.")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
