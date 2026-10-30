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
# Un CAPTCHA peut aussi protéger le formulaire « Postuler » d'une vraie page d'offre : il ne
# compte comme blocage que sur une page courte, sans offre structurée.
CAPTCHA = re.compile(
    r"g-recaptcha|h-captcha|hcaptcha\.com|cf-turnstile|/recaptcha/api|\bcaptcha\b", re.IGNORECASE,
)
SHORT_PAGE = 1500  # caractères de texte visible
LOGIN_PATH = re.compile(
    r"/(login|log-in|signin|sign-in|connexion|se-connecter|auth|sso)(/|$)", re.IGNORECASE,
)
EXPIRED_TEXT = re.compile(
    r"offre (n[’']est plus (disponible|en ligne)|a expiré|est expirée|est pourvue|est clôturée)|"
    r"annonce (n[’']est plus (disponible|en ligne)|a expiré|est expirée)|"
    r"no longer (available|accepting applications)|position has been filled|job has expired",
    re.IGNORECASE,
)
TAGS = re.compile(r"<(script|style)\b.*?</\1\s*>|<[^>]+>", re.IGNORECASE | re.DOTALL)


def visible_text(html: str) -> str:
    return " ".join(TAGS.sub(" ", html).split())


def block_cause(html: str, final_url: str, requested_url: str) -> str | None:
    """Cause du blocage (« défi anti-bot », « CAPTCHA », « page de connexion ») ou None."""
    if CHALLENGE.search(html):
        return "défi anti-bot"
    if CAPTCHA.search(html) and '"JobPosting"' not in html and (
        len(visible_text(html)) < SHORT_PAGE
    ):
        return "CAPTCHA"
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
    if len(value.strip()) == 10:  # « 2026-10-31 »
        until += dt.timedelta(days=1)
    if until.tzinfo is None:
        until = until.replace(tzinfo=dt.UTC)
    return until < (now or dt.datetime.now(dt.UTC))


def page_says_expired(html: str) -> bool:
    return bool(EXPIRED_TEXT.search(visible_text(html)))


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
