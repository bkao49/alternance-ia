"""Robot web générique (#59) : un site = une entrée de configuration, sans code par site.

Sur chaque page, on lit d'abord les données structurées `schema.org/JobPosting` (JSON-LD) ;
sinon, les sélecteurs CSS déclarés pour le site. Toutes les requêtes passent par
`PoliteClient` (liste blanche, robots.txt, 3 s par domaine, arrêt au premier blocage).

On ne garde que l'offre (titre, entreprise, lieu, contrat, texte, lien) : jamais le nom ni le
contact d'un recruteur (`contactPoint`, `applicationContact`… ne sont pas lus).
"""

import datetime as dt
import hashlib
import json
import logging
import re
import tomllib
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any
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
    SearchQuery,
    canonical_url,
)
from app.collectors.http_client import (
    Page,
    PageNotFound,
    PoliteClient,
    RobotsDisallowed,
    UnsafeUrl,
)

log = logging.getLogger(__name__)

MAX_POSTINGS_PER_PAGE = 200
HTML_TYPES = {"text/html", "application/xhtml+xml"}
# Mots qui disent le type de contrat, cherchés dans l'intitulé et le champ contrat.
CONTRACT_WORDS = [
    (ContractType.APPRENTICESHIP, r"\baltern(ance|ant|ante)s?\b|apprenti|professionnalisation"),
    (ContractType.INTERNSHIP, r"\bstages?\b|stagiaire|\bintern(e|s|ship)?\b"),
    (ContractType.FIXED_TERM, r"\bcdd\b|\btemporary\b"),
    (ContractType.PERMANENT, r"\bcdi\b|\bpermanent\b"),
]


# --- Configuration --------------------------------------------------------------------------


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
        if value is not None:
            soupsieve.compile(value)  # lève une erreur si le sélecteur est invalide
        return value


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
        if value is not None:
            soupsieve.compile(value)
        return value

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
        try:
            data = json.loads(script.get_text())
        except ValueError:
            continue  # bloc mal formé : ignoré, les autres sont lus
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
    if not isinstance(value, str):
        return ""
    return BeautifulSoup(value, "html.parser").get_text("\n", strip=True)


def _name(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping) and isinstance(value.get("name"), str):
        return value["name"]
    return None


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
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)


def _short_hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()[:32]


# --- Collecteur -----------------------------------------------------------------------------


class WebCollector(Collector):
    def __init__(self, site: SiteConfig, client: PoliteClient | None = None):
        self.site = site
        self.source = site.source
        self.client = client or PoliteClient(site.source, site.allowed_domains)

    def fetch(self, query: SearchQuery) -> Iterator[Mapping[str, Any]]:
        """Pages de départ, puis pages d'offre trouvées par `offer_links`. Les filtres de
        `query` sont appliqués après coup par `collect` : un site n'a pas d'API de recherche."""
        budget, seen = self.site.max_pages, set()
        for start in self.site.start_urls:
            if budget <= 0:
                return
            budget -= 1
            page = self._page(start)
            if page is None:
                continue
            soup = BeautifulSoup(page.text, "html.parser")
            yield from self._records(page, soup, detail=self.site.offer_links is None)
            if not self.site.offer_links:
                continue
            for link in soup.select(self.site.offer_links):
                href = link.get("href")
                if not isinstance(href, str):
                    continue
                url = urljoin(page.url, href)
                if url in seen or not in_allowlist(url, self.site.allowed_domains):
                    continue
                if budget <= 0:
                    return
                seen.add(url)
                budget -= 1
                detail = self._page(url)
                if detail is not None:
                    yield from self._records(detail, BeautifulSoup(detail.text, "html.parser"))

    def _page(self, url: str) -> Page | None:
        """Page HTML, ou None si elle est ignorée seule. Un blocage (`SourceBlocked`,
        `QuotaExceeded`) ou une panne remonte et arrête la source."""
        try:
            page = self.client.get(url)
        except (UnsafeUrl, RobotsDisallowed, PageNotFound, InvalidResponse) as exc:
            log.warning("collector=%s page ignorée (%s)", self.source, type(exc).__name__)
            return None
        if page.content_type not in HTML_TYPES:
            log.warning("collector=%s page ignorée (type %s)", self.source, page.content_type)
            return None
        return page

    def _records(
        self, page: Page, soup: BeautifulSoup, detail: bool = True,
    ) -> Iterator[Mapping[str, Any]]:
        postings = job_postings(soup)
        for posting in postings:
            yield {"kind": "jsonld", "page_url": page.url, "data": posting}
        if not postings and detail and self.site.selectors:
            fields = {}
            for name, selector in self.site.selectors.model_dump().items():
                element = soup.select_one(selector) if selector else None
                separator = "\n" if name == "description" else " "
                fields[name] = element.get_text(separator, strip=True) if element else None
            if fields.get("title"):
                yield {"kind": "css", "page_url": page.url, "fields": fields}

    def normalize(self, raw: Mapping[str, Any]) -> NormalizedOffer:
        page_url = raw.get("page_url")
        if not isinstance(page_url, str):
            raise InvalidResponse(self.source, "enregistrement sans page d'origine")
        if raw.get("kind") == "css":
            fields = raw["fields"]
            return NormalizedOffer(
                source=self.source, external_id=_short_hash(canonical_url(page_url)),
                url=page_url, title=fields["title"],
                company=fields.get("company") or self.site.company or "",
                location=fields.get("location"),
                contract_type=contract_type(fields["title"], fields.get("contract")),
                description_text=fields.get("description") or "",
            )
        data = raw.get("data")
        if not isinstance(data, Mapping) or not isinstance(data.get("title"), str):
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
            and str(identifier).strip() else _short_hash(canonical_url(url), data["title"], company)
        )
        return NormalizedOffer(
            source=self.source, external_id=external_id[:200], url=url, title=data["title"],
            company=company, location=city,
            contract_type=contract_type(data["title"], data.get("employmentType")),
            description_text=html_to_text(data.get("description")),
            published_at=parse_date(data.get("datePosted")),
        )
