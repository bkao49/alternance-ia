"""Robot web générique (#59) : un site = une entrée de configuration, sans code par site.

Sur chaque page, on lit d'abord les données structurées `schema.org/JobPosting` (JSON-LD) ;
sinon, les sélecteurs CSS déclarés pour le site. Toutes les requêtes passent par
`PoliteClient` (liste blanche, robots.txt, 3 s par domaine, arrêt au premier blocage).

On ne garde que l'offre (titre, entreprise, lieu, contrat, texte, lien) : jamais le nom ni le
contact d'un recruteur (`contactPoint`, `applicationContact`… ne sont pas lus).
"""

import datetime as dt
import hashlib
import html
import json
import logging
import re
import tomllib
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any, Self
from urllib.parse import urljoin, urlsplit

import soupsieve
from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.collectors.base import (
    SOURCE_PATTERN,
    Collector,
    ContractType,
    InvalidResponse,
    NormalizedOffer,
    OfferExpired,
    SearchQuery,
    SourceBlocked,
    canonical_url,
)
from app.collectors.detection import has_captcha, posting_expired, text_says_expired
from app.collectors.http_client import Page, PageNotFound, PageSkipped, PoliteClient

log = logging.getLogger(__name__)

MAX_POSTINGS_PER_PAGE = 200
MAX_JSONLD = 500_000  # caractères par bloc JSON-LD
MAX_TAGS = 50_000  # au-delà, la page n'est pas analysée
HTML_TYPES = {"text/html", "application/xhtml+xml"}
HOST_NAME = re.compile(r"[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+")
BROAD_SECOND_LEVEL = {"co", "com", "org", "net", "gouv", "gov", "ac", "edu", "asso"}
# Mots qui disent le type de contrat, cherchés dans l'intitulé et le champ contrat.
CONTRACT_WORDS = [
    (ContractType.APPRENTICESHIP, r"\baltern(ance|ant|ante)s?\b|apprenti|professionnalisation"),
    (ContractType.INTERNSHIP, r"\bstages?\b|stagiaire|\binterns?\b|\binternship\b"),
    (ContractType.FIXED_TERM, r"\bcdd\b|\btemporary\b"),
    (ContractType.PERMANENT, r"\bcdi\b|\bpermanent\b"),
]


# --- Configuration --------------------------------------------------------------------------


def _css(value: str | None) -> str | None:
    if value is not None:
        try:
            soupsieve.compile(value)
        except soupsieve.SelectorSyntaxError as exc:
            raise ValueError("sélecteur CSS invalide") from exc
    return value


class Selectors(BaseModel):
    """Sélecteurs CSS de repli, appliqués aux pages d'offre sans JSON-LD."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str
    company: str | None = None
    location: str | None = None
    contract: str | None = None
    description: str | None = None

    @field_validator("*")
    @classmethod
    def _valid_css(cls, value: str | None) -> str | None:
        return _css(value)


class SiteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(pattern=SOURCE_PATTERN)
    company: str | None = None  # entreprise par défaut (page carrières d'une seule entreprise)
    allowed_domains: tuple[str, ...] = Field(min_length=1, max_length=10)
    start_urls: tuple[str, ...] = Field(min_length=1, max_length=20)
    offer_links: str | None = None  # sélecteur CSS des liens vers les pages d'offre
    max_pages: int = Field(default=50, ge=1, le=200)
    selectors: Selectors | None = None

    @field_validator("offer_links")
    @classmethod
    def _valid_css(cls, value: str | None) -> str | None:
        return _css(value)

    @field_validator("allowed_domains")
    @classmethod
    def _valid_domains(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        domains = tuple(d.strip().strip(".").lower() for d in value)
        for domain in domains:
            if not HOST_NAME.fullmatch(domain) or domain.rsplit(".", 1)[-1].isdigit():
                raise ValueError("domaine invalide (nom attendu, ni IP ni joker)")
            # « example.com » oui ; « com », « co.uk » ou « gouv.fr » ouvriraient trop large.
            labels = domain.split(".")
            if len(labels) == 2 and labels[0] in BROAD_SECOND_LEVEL:
                raise ValueError("domaine trop large")
        return domains

    @model_validator(mode="after")
    def _start_urls_in_allowlist(self) -> "SiteConfig":
        for url in self.start_urls:
            if not in_allowlist(url, self.allowed_domains):
                raise ValueError("URL de départ hors des domaines autorisés")
        return self


def load_sites(path: Path) -> list[SiteConfig]:
    """Lit un fichier TOML de sites (`[[site]]`). Un site présent ici est un site activé :
    il doit avoir sa fiche `docs/sources/<source>.md` approuvée par le PO."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    sites = [SiteConfig(**site) for site in data.get("site", [])]
    if len({s.source for s in sites}) != len(sites):
        raise ValueError("deux sites ont le même identifiant de source")
    return sites


def _url_key(url: str) -> str | None:
    try:
        return canonical_url(url)
    except ValueError:
        return None


def in_allowlist(url: str, domains: Iterable[str]) -> bool:
    try:
        host = urlsplit(canonical_url(url)).hostname or ""
    except ValueError:
        return False
    return any(host == d or host.endswith("." + d) for d in (x.lower() for x in domains))


# --- Extraction -----------------------------------------------------------------------------


def job_postings(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Objets JobPosting des blocs JSON-LD (y compris dans `@graph` ou une `ItemList`)."""
    found: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.IGNORECASE)}):
        block = script.get_text()
        if len(block) > MAX_JSONLD:
            continue
        try:
            data = json.loads(block)
        except (ValueError, RecursionError):
            continue  # bloc mal formé ou piégé (imbrication extrême) : ignoré seul
        _walk(data, found, depth=0)
    return found[:MAX_POSTINGS_PER_PAGE]


def _walk(node: Any, found: list[dict[str, Any]], depth: int) -> None:
    if depth > 6 or len(found) >= MAX_POSTINGS_PER_PAGE:
        return
    if isinstance(node, list):
        for item in node:
            _walk(item, found, depth + 1)
    elif isinstance(node, dict):
        types = node.get("@type")
        if "JobPosting" in (types if isinstance(types, list) else [types]):
            found.append(node)
            return
        for key in ("@graph", "itemListElement", "item", "mainEntity"):
            if key in node:
                _walk(node[key], found, depth + 1)


def html_to_text(value: Any) -> str:
    """Texte brut ; une seconde passe pour une description doublement échappée (`&lt;p&gt;`)."""
    if not isinstance(value, str):
        return ""
    text = BeautifulSoup(value, "html.parser").get_text("\n", strip=True)
    if "<" in text:
        text = BeautifulSoup(text, "html.parser").get_text("\n", strip=True)
    return text


def _plain(value: Any) -> str | None:
    return html.unescape(value) if isinstance(value, str) else None


def _name(value: Any) -> str | None:
    if isinstance(value, Mapping):
        value = value.get("name")
    return _plain(value)


def _city(location: Any) -> str | None:
    """Ville du premier lieu : `jobLocation.address.addressLocality`."""
    if isinstance(location, list):
        location = location[0] if location else None
    if not isinstance(location, Mapping):
        return None
    address = location.get("address")
    if isinstance(address, Mapping):
        city = address.get("addressLocality")
        return city if isinstance(city, str) else None
    return address if isinstance(address, str) else None


def contract_type(*texts: Any) -> ContractType:
    joined = " ".join(
        " ".join(map(str, t)) if isinstance(t, list) else str(t) for t in texts if t
    )
    for kind, pattern in CONTRACT_WORDS:
        if re.search(pattern, joined, re.IGNORECASE):
            return kind
    return ContractType.OTHER


def parse_date(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if not 2000 <= parsed.year <= dt.datetime.now(dt.UTC).year + 1:
        return None  # date absurde (« 0001-01-01 ») : ignorée
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _short_hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]


# --- Collecteur -----------------------------------------------------------------------------


class WebCollector(Collector):
    def __init__(self, site: SiteConfig, client: PoliteClient | None = None):
        self.site = site
        self.source = site.source
        self.client = client or PoliteClient(site.source, site.allowed_domains)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.client.close()

    def fetch(self, query: SearchQuery) -> Iterator[Mapping[str, Any]]:
        """Pages de départ, puis pages d'offre trouvées par `offer_links`. Les filtres de
        `query` sont appliqués après coup par `collect` : un site n'a pas d'API de recherche.

        Avec `offer_links`, les offres résumées sur les pages de liste ne sortent qu'après les
        pages d'offre : à identifiant égal, `collect` garde la version complète."""
        budget = self.site.max_pages
        seen = {_url_key(u) for u in self.site.start_urls}
        listed: list[Mapping[str, Any]] = []
        for start in self.site.start_urls:
            if budget <= 0:
                break
            budget -= 1
            page, soup = self._parsed(start)
            if page is None or soup is None:
                continue
            records = list(self._records(page, soup, detail=self.site.offer_links is None))
            links = soup.select(self.site.offer_links) if self.site.offer_links else []
            if not records and not links:
                self._stop_on_captcha(page)
            if not self.site.offer_links:
                yield from records
                continue
            listed.extend(records)
            for link in links:
                href = link.get("href")
                url = urljoin(page.url, href) if isinstance(href, str) else ""
                key = _url_key(url)  # « #postuler » ou « ?utm_… » : même page
                if key is None or key in seen or not in_allowlist(url, self.site.allowed_domains):
                    continue
                if budget <= 0:
                    break
                seen.add(key)
                budget -= 1
                detail, detail_soup = self._parsed(url)
                if detail is not None and detail_soup is not None:
                    found = list(self._records(detail, detail_soup))
                    if not found:
                        self._stop_on_captcha(detail)
                    yield from found
        yield from listed

    def _stop_on_captcha(self, page: Page) -> None:
        """Un CAPTCHA à la place du contenu attendu (ni offre ni lien) : la source s'arrête.
        Un CAPTCHA à côté d'une offre lisible (formulaire « Postuler ») ne compte pas."""
        if has_captcha(page.text):
            raise SourceBlocked(self.source, "CAPTCHA")

    def _parsed(self, url: str) -> tuple[Page | None, BeautifulSoup | None]:
        """Page et arbre HTML ; une page aux balises innombrables est ignorée avant l'analyse,
        dont le coût croît avec leur nombre."""
        page = self._page(url)
        if page is None:
            return None, None
        if page.text.count("<") > MAX_TAGS:
            log.warning("collector=%s page ignorée (trop de balises)", self.source)
            return page, None
        return page, BeautifulSoup(page.text, "html.parser")

    def _page(self, url: str) -> Page | None:
        """Page HTML, ou None si elle est ignorée seule (`PageSkipped` : hors liste, robots.txt,
        404, trop grande). Un blocage, un quota ou une panne remonte et arrête la source."""
        try:
            page = self.client.get(url)
        except PageSkipped as exc:
            log.warning("collector=%s page ignorée (%s)", self.source, type(exc).__name__)
            return None
        if page.content_type not in HTML_TYPES:
            log.warning("collector=%s page ignorée (type non HTML)", self.source)
            return None
        return page

    def _records(
        self, page: Page, soup: BeautifulSoup, detail: bool = True,
    ) -> Iterator[Mapping[str, Any]]:
        postings = job_postings(soup)
        # Bandeau « offre pourvue » : lu une fois par page d'offre (sur une liste, il viserait
        # une autre offre). get_text ignore scripts et styles.
        expired = detail and text_says_expired(soup.get_text(" "))
        for posting in postings:
            yield {"kind": "jsonld", "page_url": page.url, "data": posting, "expired": expired}
        if not postings and detail and self.site.selectors:
            fields = {}
            for name, selector in self.site.selectors.model_dump().items():
                element = soup.select_one(selector) if selector else None
                separator = "\n" if name == "description" else " "
                fields[name] = element.get_text(separator, strip=True) if element else None
            if fields.get("title"):
                yield {"kind": "css", "page_url": page.url, "fields": fields, "expired": expired}

    def check_expired(self, url: str) -> bool | None:
        """Relit la page d'une offre enregistrée : 404/410, date limite passée ou mention
        « offre pourvue » → expirée. Page illisible ou interdite → None (on ne sait pas)."""
        try:
            page = self.client.get(url)
        except PageNotFound:
            return True
        except PageSkipped:
            return None
        if page.content_type not in HTML_TYPES or page.text.count("<") > MAX_TAGS:
            return None
        soup = BeautifulSoup(page.text, "html.parser")
        if any(posting_expired(p) for p in job_postings(soup)):
            return True
        return text_says_expired(soup.get_text(" "))

    def normalize(self, raw: Mapping[str, Any]) -> NormalizedOffer:
        page_url = raw.get("page_url")
        if not isinstance(page_url, str):
            raise InvalidResponse(self.source, "enregistrement sans page d'origine")
        if raw.get("kind") == "css":
            fields = raw["fields"]
            if raw.get("expired"):
                raise OfferExpired(self.source, _short_hash(canonical_url(page_url)))
            return NormalizedOffer(
                source=self.source, external_id=_short_hash(canonical_url(page_url)),
                url=page_url, title=fields["title"],
                company=fields.get("company") or self.site.company or "",
                location=fields.get("location"),
                contract_type=contract_type(fields["title"], fields.get("contract")),
                description_text=fields.get("description") or "",
            )
        data = raw.get("data")
        title = _plain(data.get("title")) if isinstance(data, Mapping) else None
        if not isinstance(data, Mapping) or not title:
            raise InvalidResponse(self.source, "JobPosting sans intitulé")
        # Le lien déclaré n'est gardé que s'il reste sur le site ; sinon, la page lue.
        declared = urljoin(page_url, data["url"]) if isinstance(data.get("url"), str) else None
        url = declared if declared and in_allowlist(declared, self.site.allowed_domains) else page_url
        identifier = data.get("identifier")
        if isinstance(identifier, Mapping):
            identifier = identifier.get("value")
        city = _city(data.get("jobLocation"))
        if city is None and data.get("jobLocationType") == "TELECOMMUTE":
            city = "Télétravail"
        company = _name(data.get("hiringOrganization")) or self.site.company or ""
        external_id = (
            str(identifier) if isinstance(identifier, str | int) and not isinstance(identifier, bool)
            and str(identifier).strip() else self._fallback_id(url, page_url, title, company)
        )
        if raw.get("expired") or posting_expired(data):
            raise OfferExpired(self.source, external_id[:200])
        return NormalizedOffer(
            source=self.source, external_id=external_id[:200], url=url, title=title,
            company=company, location=city,
            contract_type=contract_type(title, data.get("employmentType")),
            description_text=html_to_text(data.get("description")),
            published_at=parse_date(data.get("datePosted")),
        )

    @staticmethod
    def _fallback_id(url: str, page_url: str, title: str, company: str) -> str:
        """Sans `identifier` : l'URL propre de l'offre suffit (un intitulé corrigé reste la même
        offre) ; plusieurs offres sur une même page se distinguent par titre et entreprise."""
        if canonical_url(url) != canonical_url(page_url):
            return _short_hash(canonical_url(url))
        return _short_hash(canonical_url(url), title, company)
