"""Détection de blocage et d'annonce expirée (#14).

Jamais de contournement : un blocage détecté arrête la source, sa cause (un texte fixe, jamais
le contenu de la page) est journalisée et notifiée au PO. Une annonce expirée n'est pas
collectée, et une offre déjà enregistrée dont la page a disparu est marquée `expired`.
"""

import datetime as dt
import logging
import re
from collections.abc import Iterable, Mapping
from typing import Any, Protocol
from urllib.parse import urlsplit

from app.collectors.base import CollectResult, SourceBlocked

log = logging.getLogger(__name__)

# Marqueurs propres aux pages de défi (Cloudflare, Incapsula, DataDome…), jamais présents sur
# une page normale du même site : leur seule présence suffit.
CHALLENGE = re.compile(
    r"<title>\s*(just a moment|attention required|un instant)|cf_chl_opt|"
    r"checking your browser before|_incapsula_resource|captcha-delivery\.com|px-captcha",
    re.IGNORECASE,
)
# Widget CAPTCHA visible. Il protège souvent le formulaire « Postuler » d'une vraie offre : le
# collecteur ne le compte comme blocage que si la page ne donne ni offre ni lien (`has_captcha`).
CAPTCHA = re.compile(r"g-recaptcha|h-captcha|cf-turnstile", re.IGNORECASE)
LOGIN_PATH = re.compile(
    r"/(login|log-in|signin|sign-in|connexion|se-connecter|auth|sso)(/|$)", re.IGNORECASE,
)
# Tournures ancrées sur l'offre elle-même : « until the position has been filled » (offre
# ouverte) ne doit pas compter.
EXPIRED_TEXT = re.compile(
    r"(cette|l[’'])\s?(offre|annonce) (n[’']est plus (disponible|en ligne)|a expiré|"
    r"est expirée|est pourvue|a été pourvue|est clôturée)|"
    r"this (job|position|vacancy|offer|posting) (is no longer available|has been filled|"
    r"has expired|is closed)",
    re.IGNORECASE,
)
TAG = re.compile(r"<[^<>]*>")  # linéaire : ne revient jamais en arrière au-delà d'un « < »
MAX_SCAN = 500_000  # caractères examinés : le début de page suffit pour un bandeau ou un défi


def visible_text(html: str) -> str:
    """Texte hors balises, scripts et styles, en temps linéaire (aucune expression qui
    reparcourrait la page à chaque `<` non fermé)."""
    html = html[:MAX_SCAN]
    lower, parts, pos = html.lower(), [], 0
    while (start := _next_block(lower, pos)) != -1:
        parts.append(html[pos:start])
        tag = "script" if lower.startswith("<script", start) else "style"
        end = lower.find(f"</{tag}", start)
        pos = len(html) if end == -1 else end + len(tag) + 2
    parts.append(html[pos:])
    return " ".join(TAG.sub(" ", " ".join(parts)).split())


def _next_block(lower: str, pos: int) -> int:
    found = [i for i in (lower.find("<script", pos), lower.find("<style", pos)) if i != -1]
    return min(found) if found else -1


def has_captcha(html: str) -> bool:
    return bool(CAPTCHA.search(html[:MAX_SCAN]))


def block_cause(html: str, final_url: str, requested_url: str) -> str | None:
    """Cause d'un blocage certain (« défi anti-bot », « page de connexion ») ou None."""
    if CHALLENGE.search(html[:MAX_SCAN]):
        return "défi anti-bot"
    # Redirigé vers une page de connexion : on ne se connecte jamais.
    if LOGIN_PATH.search(urlsplit(final_url).path) and not LOGIN_PATH.search(
        urlsplit(requested_url).path
    ):
        return "page de connexion"
    return None


def posting_expired(posting: Mapping[str, Any], now: dt.datetime | None = None) -> bool:
    """JSON-LD `validThrough` dépassé. Date seule : valable jusqu'à la fin du jour."""
    value = posting.get("validThrough")
    if not isinstance(value, str):
        return False
    try:
        until = dt.datetime.fromisoformat(value.strip())
    except ValueError:
        return False
    if "T" not in value and " " not in value.strip():  # date seule (« 2026-10-31 », « 20261031 »)
        until += dt.timedelta(days=1)
    if until.tzinfo is None:  # heure sans fuseau : supposée UTC (1 à 2 h d'écart avec Paris)
        until = until.replace(tzinfo=dt.UTC)
    return until < (now or dt.datetime.now(dt.UTC))


def text_says_expired(text: str) -> bool:
    return bool(EXPIRED_TEXT.search(text[:MAX_SCAN]))


def page_says_expired(html: str) -> bool:
    return text_says_expired(visible_text(html))


# --- Blocage d'une source -------------------------------------------------------------------


class Notifier(Protocol):
    def notify(self, source: str, cause: str) -> None: ...


class LogNotifier:
    """Notification par défaut : le journal. Telegram ou e-mail viendront avec #25."""

    def notify(self, source: str, cause: str) -> None:
        log.error("NOTIFICATION source=%s bloquée (%s) : désactivée, aucun contournement",
                  source, cause)


def handle_blocks(
    results: Iterable[CollectResult], disabled: set[str], notifier: Notifier,
) -> list[str]:
    """Désactive chaque source bloquée (ajoutée à `disabled`) et notifie une fois par source.
    Renvoie les sources nouvellement bloquées. `disabled` sera persisté par le planificateur."""
    newly = []
    for result in results:
        if isinstance(result.error, SourceBlocked) and result.source not in disabled:
            disabled.add(result.source)
            newly.append(result.source)
            log.error("collector=%s désactivé : %s", result.source, result.error.message)
            notifier.notify(result.source, result.error.message)
    return newly
