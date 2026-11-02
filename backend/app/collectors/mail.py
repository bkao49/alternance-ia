"""Collecteur d'alertes e-mail (`docs/sources/email.md`) : offres lues dans la boîte dédiée aux alertes.

Le contenu d'un e-mail est une donnée non fiable : on ne lit que du texte et des liens, on n'exécute
rien, on ne suit aucun lien (il est gardé pour que l'utilisateur ouvre l'offre lui-même). La boîte est
lue derrière `MailClient` (client IMAP réel, ou faux client en test). Rien n'est jamais supprimé :
un e-mail traité reçoit seulement le drapeau « lu ».
"""

import email
import email.policy
import hashlib
import imaplib
import logging
import os
import re
import ssl
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from email.utils import getaddresses
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from app.collectors.base import (
    Collector,
    CollectorError,
    InvalidResponse,
    NetworkError,
    NormalizedOffer,
    SearchQuery,
    canonical_url,
)
from app.collectors.web import contract_type

log = logging.getLogger(__name__)

MAX_MESSAGE_BYTES = 2_000_000
MAX_MESSAGES = 200  # par collecte
MAX_OFFERS_PER_MESSAGE = 50
# Paramètres de suivi propres aux alertes (en plus de ceux retirés par `canonical_url`).
TRACKING_PARAMS = re.compile(
    r"^(tk|from|alid|trk|trackingid|refid|midtoken|midsig|eid|lipi|ref|src|source|campaign|otptoken)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Template:
    """Où trouver les offres dans les e-mails d'un site : sélecteurs CSS appliqués à chaque carte.

    Gabarits écrits d'après des e-mails fictifs ; à ajuster sur un vrai e-mail reçu (fiche source)."""

    name: str
    domains: tuple[str, ...]  # domaines d'envoi ET domaines acceptés pour les liens
    card: str
    title: str
    company: str
    location: str
    contract: str | None = None
    link: str = "a[href]"


TEMPLATES = (
    Template("indeed", ("indeed.com",), "tr.job", "a.jt", ".co", ".loc", ".type"),
    Template("linkedin", ("linkedin.com",), "td.card", "a.title", ".company", ".place"),
    Template("wttj", ("welcometothejungle.com",), "div.offer", "h3 a", "p.org", "p.where", "p.kind"),
    Template("jobteaser", ("jobteaser.com",), "li.item", "a.name", "span.employer", "span.city", "span.contract"),
    Template("hellowork", ("hellowork.com",), "article.ad", "a.heading", "div.firm", "div.town", "div.deal"),
    Template("francetravail", ("francetravail.fr",), "div.annonce", "a.intitule", "span.ent", "span.lieu", "span.nature"),
    Template("adzuna", ("adzuna.fr", "adzuna.com"), "div.result", "a.t", "span.c", "span.l"),
)


def domain_matches(host: str, domains: Sequence[str]) -> bool:
    """`host` est l'un des domaines ou un de leurs sous-domaines (pas « indeed.com.evil.test »)."""
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in domains)


@dataclass(frozen=True)
class MailMessage:
    uid: str
    sender: str  # adresse de l'unique en-tête From, en minuscules ; "" si absente ou ambiguë
    auth_results: tuple[str, ...]  # en-têtes Authentication-Results, le plus récent d'abord
    html: str


def parse_message(uid: str, raw: bytes) -> MailMessage:
    """Octets d'un e-mail → MailMessage. Seule la partie HTML est gardée ; pièces jointes ignorées."""
    msg = email.message_from_bytes(raw[:MAX_MESSAGE_BYTES], policy=email.policy.default)
    froms = msg.get_all("From") or []
    addresses = getaddresses([str(f) for f in froms])
    sender = addresses[0][1].lower() if len(froms) == 1 and len(addresses) == 1 else ""
    auth = tuple(str(a) for a in msg.get_all("Authentication-Results") or [])
    part = msg.get_body(preferencelist=("html",))
    html = part.get_content() if part is not None else ""
    return MailMessage(uid, sender, auth, html if isinstance(html, str) else "")


class MailClient(Protocol):
    def unseen(self, sender_domains: Sequence[str], limit: int) -> Iterator[MailMessage]:
        """E-mails non lus envoyés depuis ces domaines (le collecteur revérifie l'expéditeur)."""

    def mark_processed(self, uid: str) -> None:
        """Marque l'e-mail comme lu. Aucune méthode ne supprime : c'est voulu."""

    def close(self) -> None: ...


class ImapMailClient:
    """Client IMAP réel (TLS). Lecture avec BODY.PEEK, puis drapeau \\Seen : jamais de suppression."""

    def __init__(self, host: str, user: str, password: str, port: int = 993, folder: str = "INBOX",
                 factory: Callable[..., Any] | None = None):
        self.folder = folder
        try:
            factory = factory or imaplib.IMAP4_SSL
            self.imap = factory(host, port, ssl_context=ssl.create_default_context(), timeout=30)
            self.imap.login(user, password)
            if self.imap.select(folder)[0] != "OK":
                raise imaplib.IMAP4.error("dossier introuvable")
        except imaplib.IMAP4.error:  # le message du serveur peut citer l'identifiant : pas repris
            self.close()
            raise CollectorError("email", "identifiants IMAP refusés") from None
        except (OSError, ssl.SSLError) as exc:
            self.close()
            raise NetworkError("email", "connexion IMAP impossible") from exc

    def unseen(self, sender_domains: Sequence[str], limit: int) -> Iterator[MailMessage]:
        uids: list[bytes] = []
        for domain in sender_domains:
            if not re.fullmatch(r"[a-z0-9.-]+", domain):
                continue  # jamais de caractère d'injection dans la commande SEARCH
            _, data = self.imap.search(None, "UNSEEN", "FROM", f'"{domain}"')
            uids += data[0].split() if data and data[0] else []
        # Les plus récents d'abord : d'anciens e-mails écartés ne bloquent pas les alertes à venir.
        for uid in sorted(set(uids), key=int, reverse=True)[:limit]:
            _, size = self.imap.fetch(uid, "(RFC822.SIZE)")
            found = re.search(rb"RFC822\.SIZE (\d+)", size[0] if isinstance(size[0], bytes) else b"")
            if not found or int(found.group(1)) > MAX_MESSAGE_BYTES:
                self.mark_processed(uid.decode())  # trop gros : écarté (marqué lu, jamais supprimé)
                continue
            _, data = self.imap.fetch(uid, "(BODY.PEEK[])")
            if data and isinstance(data[0], tuple):
                try:
                    message = parse_message(uid.decode(), data[0][1])
                except Exception as exc:  # noqa: BLE001 (e-mail illisible : écarté seul, rien n'est repris)
                    log.warning("collector=email e-mail illisible écarté (%s)", type(exc).__name__)
                    self.mark_processed(uid.decode())
                    continue
                yield message

    def mark_processed(self, uid: str) -> None:
        self.imap.store(uid, "+FLAGS", "(\\Seen)")

    def close(self) -> None:
        try:
            self.imap.logout()  # pas de EXPUNGE ni de CLOSE : rien n'est jamais purgé
        except (AttributeError, OSError, imaplib.IMAP4.error):
            pass


def _clean_link(href: str, domains: Sequence[str]) -> str:
    """Lien https vers le site de l'alerte, sans paramètres de suivi ; sinon ValueError."""
    parts = urlsplit(href.strip())
    if parts.scheme.lower() != "https" or not domain_matches(parts.hostname or "", domains):
        raise ValueError("lien hors du site de l'alerte")
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not TRACKING_PARAMS.match(k)])
    return canonical_url(urlunsplit((parts.scheme, parts.netloc, parts.path, query, "")))


def _text(card: Any, selector: str | None) -> str:
    node = card.select_one(selector) if selector else None
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


class EmailCollector(Collector):
    source = "email"

    def __init__(self, client: MailClient | None = None, require_auth: bool | None = None):
        self._client = client
        env = os.environ
        self.require_auth = (env.get("EMAIL_ALERTS_REQUIRE_AUTH", "true").lower() != "false"
                             if require_auth is None else require_auth)
        self.authserv_id = env.get("EMAIL_ALERTS_AUTHSERV_ID", "").strip().lower()
        # Domaines d'envoi réglables par site (EMAIL_ALERTS_DOMAINS_INDEED=indeed.com,mail.indeed.com).
        self.templates = tuple(
            replace(t, domains=tuple(d.strip().lower() for d in custom.split(",") if d.strip()) or t.domains)
            for t in TEMPLATES for custom in [env.get(f"EMAIL_ALERTS_DOMAINS_{t.name.upper()}", "")]
        )

    def _connect(self) -> MailClient:
        if self._client:
            return self._client
        host, user, password = (os.environ.get(f"EMAIL_ALERTS_{k}", "") for k in ("HOST", "USER", "PASSWORD"))
        if not (host and user and password):
            raise CollectorError(self.source, "boîte d'alertes non configurée (EMAIL_ALERTS_*)")
        return ImapMailClient(host, user, password, int(os.environ.get("EMAIL_ALERTS_PORT") or 993),
                              os.environ.get("EMAIL_ALERTS_FOLDER") or "INBOX")

    def _template(self, message: MailMessage) -> Template | None:
        domain = message.sender.rpartition("@")[2]
        if not message.sender or not domain:
            return None
        found = next((t for t in self.templates if domain_matches(domain, t.domains)), None)
        if found is None or not self._authenticated(message, domain):
            return None
        return found

    def _authenticated(self, message: MailMessage, domain: str) -> bool:
        """DMARC réussi, ou DKIM réussi signé par le domaine de l'expéditeur (un From se falsifie)."""
        if not self.require_auth:
            return True
        # Seul l'en-tête ajouté par NOTRE serveur compte : le plus récent, ou celui dont l'identifiant de
        # serveur (premier mot) est EMAIL_ALERTS_AUTHSERV_ID. Un en-tête posé par l'expéditeur est ignoré.
        headers = message.auth_results
        if self.authserv_id:
            headers = tuple(h for h in headers if h.split(";", 1)[0].strip().lower() == self.authserv_id)
        results = headers[0].lower() if headers else ""
        if re.search(r"\bdmarc=pass\b", results):
            return True
        signer = re.search(r"\bdkim=pass\b[^;]*header\.d=([a-z0-9.-]+)", results)
        if not signer:
            return False
        return domain_matches(domain, (signer.group(1),)) or domain_matches(signer.group(1), (domain,))

    def fetch(self, query: SearchQuery) -> Iterator[Mapping[str, Any]]:
        client = self._connect()
        domains = [d for t in self.templates for d in t.domains]
        try:
            for message in client.unseen(domains, MAX_MESSAGES):
                template = self._template(message)
                if template is None:
                    log.info("collector=email e-mail écarté (expéditeur non reconnu ou non authentifié)")
                    client.mark_processed(message.uid)  # marqué lu pour ne pas être relu ; jamais supprimé
                    continue
                try:
                    cards = BeautifulSoup(message.html, "html.parser").select(template.card)
                except RecursionError:  # HTML imbriqué à l'excès : écarté seul
                    cards = []
                if not cards:
                    log.warning("collector=email aucun résultat avec le gabarit %s (gabarit périmé ?)", template.name)
                for card in cards[:MAX_OFFERS_PER_MESSAGE]:
                    title_node = card.select_one(template.title)
                    link = title_node if title_node is not None and title_node.get("href") else card.select_one(template.link)
                    yield {
                        "site": template.name, "domains": template.domains,
                        "title": _text(card, template.title), "company": _text(card, template.company),
                        "location": _text(card, template.location), "contract": _text(card, template.contract),
                        "href": link.get("href", "") if link else "",
                    }
                client.mark_processed(message.uid)
        finally:
            client.close()

    def normalize(self, raw: Mapping[str, Any]) -> NormalizedOffer:
        if not raw.get("title"):
            raise InvalidResponse(self.source, "offre sans titre")
        try:
            url = _clean_link(str(raw.get("href", "")), raw["domains"])
        except ValueError as exc:
            raise InvalidResponse(self.source, "lien absent ou hors du site de l'alerte") from exc
        return NormalizedOffer(
            source=self.source, external_id=hashlib.sha256(url.encode()).hexdigest()[:32], url=url,
            title=raw["title"], company=raw.get("company") or "Entreprise non communiquée",
            location=raw.get("location") or None,
            contract_type=contract_type(raw["title"], raw.get("contract")),
        )
