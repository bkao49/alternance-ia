"""Source « web » : les pages carrières que l'utilisateur donne au robot web générique (#127).

Chaque page est une URL que le robot lit (JSON-LD `JobPosting`) avec `PoliteClient` : domaine limité à
celui de la page, adresse publique seulement, `robots.txt`, 3 s entre deux requêtes, arrêt au premier
blocage. Ici, on valide les URL à l'enregistrement (http/https, ni adresse locale ni IP, ni site fermé)
et on construit le collecteur du worker pour un utilisateur. Le client refait les contrôles réseau à
chaque requête : la validation ne remplace pas ce garde-fou, elle donne un retour immédiat.
"""
import ipaddress
import logging
from collections.abc import Callable, Iterable
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import Connection, text

from app.auth import Session, current_session, require_csrf
from app.collectors.base import Collector, canonical_url
from app.collectors.http_client import PoliteClient, is_public_address, system_resolver
from app.collectors.web import SiteConfig, WebCollector
from app.db import user_scope
from app.errors import ApiError

log = logging.getLogger(__name__)
router = APIRouter(tags=["sources"])

WEB_SOURCE = "web"
MAX_PAGES = 10  # SiteConfig accepte au plus 10 domaines
# Sites fermés (AGENTS.md) : jamais de collecte directe, on passe par les alertes e-mail.
CLOSED_SITES = ("linkedin.com", "indeed.com", "indeed.fr", "glassdoor.com", "glassdoor.fr", "apec.fr")
LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".intranet", ".corp")


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def check_hostname(host: str) -> None:
    """Refuse une adresse IP, un nom local ou interne : `ValueError` avec un message pour l'utilisateur."""
    host = host.lower().rstrip(".")
    if _is_ip(host.strip("[]")):
        raise ValueError("une adresse IP n'est pas acceptée : donnez le nom du site")
    if "." not in host or host.rsplit(".", 1)[-1].isdigit() or host == "localhost" or host.endswith(LOCAL_SUFFIXES):
        raise ValueError("adresse locale ou interne refusée")


def check_page_url(url: str, resolver: Callable[[str], Iterable[str]] | None = None) -> str:
    """URL canonique d'une page carrières, ou `ValueError` avec un message pour l'utilisateur."""
    try:
        clean = canonical_url(url)
    except ValueError:
        raise ValueError("adresse invalide (http ou https attendu)") from None
    parts = urlsplit(clean)
    host = parts.hostname or ""
    if parts.port is not None:
        raise ValueError("port non standard refusé")
    check_hostname(host)
    if any(host == d or host.endswith("." + d) for d in CLOSED_SITES):
        raise ValueError("site fermé aux robots : créez plutôt une alerte e-mail (écran « Mes sources »)")
    try:
        addresses = list((resolver or system_resolver)(host))
    except OSError:
        addresses = []  # introuvable ou DNS indisponible : le worker le dira ; rien à refuser ici
    if any(not is_public_address(a) for a in addresses):
        raise ValueError("adresse non publique refusée")
    return clean


def site_for(urls: list[str]) -> SiteConfig:
    hosts = list(dict.fromkeys(urlsplit(u).hostname or "" for u in urls))
    return SiteConfig(source=WEB_SOURCE, allowed_domains=tuple(hosts), start_urls=tuple(urls),
                      max_pages=len(urls))


def web_collector(conn: Connection, client_factory: Callable[[SiteConfig], PoliteClient] | None = None,
                  ) -> Collector | None:
    """Collecteur de l'utilisateur courant (RLS) ; None s'il n'a saisi aucune page valide."""
    urls = [r.url for r in conn.execute(text("SELECT url FROM web_pages ORDER BY position"))]
    if not urls:
        return None
    try:
        site = site_for(urls)
    except ValidationError:
        log.error("pages web enregistrées invalides : source ignorée")
        return None
    return WebCollector(site, client_factory(site) if client_factory else None)


class WebPages(BaseModel):
    urls: list[str]
    max: int


class WebPagesIn(BaseModel):
    """Remplacement complet de la liste ; une URL par entrée."""

    model_config = ConfigDict(extra="forbid")

    urls: list[str]


def read_pages(conn: Connection) -> dict:
    urls = [r.url for r in conn.execute(text("SELECT url FROM web_pages ORDER BY position"))]
    return {"urls": urls, "max": MAX_PAGES}


@router.get("/sources/web/pages", response_model=WebPages, operation_id="getWebPages")
def get_web_pages(session: Session = Depends(current_session)):
    with user_scope(session.user_id) as conn:
        return read_pages(conn)


@router.put("/sources/web/pages", response_model=WebPages, operation_id="updateWebPages")
def update_web_pages(body: WebPagesIn, session: Session = Depends(require_csrf)):
    urls: list[str] = []
    for number, raw in enumerate(body.urls, start=1):
        try:
            clean = check_page_url(raw)
        except ValueError as exc:
            raise ApiError(422, "validation_error", f"Page {number} : {exc}.") from None
        if clean not in urls:
            urls.append(clean)
    if len(urls) > MAX_PAGES:
        raise ApiError(422, "validation_error", f"{MAX_PAGES} pages au plus.")
    try:
        if urls:
            site_for(urls)  # mêmes règles de domaines que le collecteur (pas de domaine trop large)
    except ValidationError:
        raise ApiError(422, "validation_error", "Un des sites est trop général : donnez la page du site de l'entreprise.") from None
    with user_scope(session.user_id) as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:u))"), {"u": session.user_id})
        conn.execute(text("DELETE FROM web_pages"))
        for position, url in enumerate(urls):
            conn.execute(text("INSERT INTO web_pages (user_id, position, url) VALUES (:uid, :p, :url)"),
                         {"uid": session.user_id, "p": position, "url": url})
        if not urls:  # sans page, la source ne peut pas rester activée
            conn.execute(text("UPDATE source_settings SET enabled = false WHERE source = :s"), {"s": WEB_SOURCE})
        return read_pages(conn)
