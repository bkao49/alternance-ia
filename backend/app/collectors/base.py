"""Interface commune des collecteurs d'offres et modèle d'offre normalisé.

Le texte d'une annonce est une donnée non fiable : il est nettoyé et stocké, jamais interprété.
"""

import datetime as dt
import hashlib
import logging
import re
import unicodedata
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

log = logging.getLogger(__name__)

SOURCE_PATTERN = r"^[a-z][a-z0-9_]{1,39}$"
# Paramètres de suivi retirés de l'URL canonique (ils changent d'une diffusion à l'autre).
TRACKING_PARAMS = re.compile(r"^(utm_.*|gclid|fbclid|mc_[a-z]+|xtor)$", re.IGNORECASE)
# Caractères de contrôle, sauf tabulation et retours à la ligne.
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Formes juridiques ignorées par l'empreinte : « Globex SAS » et « GLOBEX » sont la même entreprise.
LEGAL_FORMS = {"sa", "sas", "sasu", "sarl", "eurl", "sca", "scop", "inc", "ltd", "llc", "gmbh"}


class ContractType(StrEnum):
    INTERNSHIP = "internship"  # stage
    APPRENTICESHIP = "apprenticeship"  # alternance (apprentissage ou professionnalisation)
    FIXED_TERM = "fixed_term"  # CDD
    PERMANENT = "permanent"  # CDI
    OTHER = "other"  # intérim, freelance, inconnu…


# --- Erreurs typées -------------------------------------------------------------------------


class CollectorError(Exception):
    """Erreur d'une source. `retryable` dit si l'orchestrateur peut réessayer plus tard."""

    retryable: ClassVar[bool] = False

    def __init__(self, source: str, message: str):
        super().__init__(f"[{source}] {message}")
        self.source = source
        self.message = message


class SourceBlocked(CollectorError):
    """403, défi anti-bot ou CAPTCHA : la source est arrêtée, jamais contournée."""


class QuotaExceeded(CollectorError):
    """429 ou quota journalier atteint."""

    retryable = True

    def __init__(self, source: str, message: str, retry_after: float | None = None):
        super().__init__(source, message)
        self.retry_after = retry_after


class InvalidResponse(CollectorError):
    """Réponse ou enregistrement illisible (format inattendu, champ obligatoire manquant)."""


class NetworkError(CollectorError):
    """Délai dépassé, connexion refusée, erreur 5xx."""

    retryable = True


# --- Modèle normalisé ------------------------------------------------------------------------


def clean_text(value: str) -> str:
    return CONTROL_CHARS.sub("", unicodedata.normalize("NFC", value)).strip()


def canonical_url(url: str) -> str:
    """http(s) seulement, hôte en minuscules, sans fragment ni paramètres de suivi."""
    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("URL http(s) attendue")
    params = parse_qsl(parts.query, keep_blank_values=True)
    query = [(k, v) for k, v in params if not TRACKING_PARAMS.match(k)]
    netloc = parts.hostname.lower() + (f":{parts.port}" if parts.port else "")
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, urlencode(sorted(query)), ""))


def _fold(value: str | None) -> str:
    """Minuscules, sans accents ni ponctuation : « Développeur·se  IA » → « developpeur se ia »."""
    if not value:
        return ""
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).split())


def _sha256(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


class NormalizedOffer(BaseModel):
    """Une offre, quelle que soit sa source. Correspond aux colonnes de `job_postings`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(pattern=SOURCE_PATTERN)
    external_id: str = Field(min_length=1, max_length=200)
    url: str = Field(max_length=2000)
    title: str = Field(min_length=1, max_length=300)
    company: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    contract_type: ContractType
    description_text: str = Field(default="", max_length=50_000)
    published_at: dt.datetime | None = None

    @field_validator("external_id", "title", "company", "description_text", mode="before")
    @classmethod
    def _clean(cls, value: Any) -> Any:
        return clean_text(value) if isinstance(value, str) else value

    @field_validator("location", mode="before")
    @classmethod
    def _clean_optional(cls, value: Any) -> Any:
        return (clean_text(value) or None) if isinstance(value, str) else value

    @field_validator("url")
    @classmethod
    def _canonical(cls, value: str) -> str:
        return canonical_url(value)

    @field_validator("published_at")
    @classmethod
    def _aware(cls, value: dt.datetime | None) -> dt.datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("date avec fuseau horaire attendue")
        return value

    @property
    def dedup_key(self) -> tuple[str, str]:
        """Doublon dans une même source : même (source, external_id). Contrainte UNIQUE en base."""
        return (self.source, self.external_id)

    @property
    def fingerprint(self) -> str:
        """Doublon entre sources : mêmes titre, entreprise, lieu et type de contrat, repliés."""
        company = " ".join(w for w in _fold(self.company).split() if w not in LEGAL_FORMS)
        return _sha256(_fold(self.title), company, _fold(self.location), self.contract_type.value)

    @property
    def content_hash(self) -> str:
        """Change quand le texte de l'annonce change (colonne `content_hash`)."""
        return _sha256(self.title, self.company, self.location or "", self.description_text)


# --- Interface ------------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchQuery:
    keywords: tuple[str, ...] = ()
    location: str | None = None
    contract_types: frozenset[ContractType] = frozenset()  # vide = tous les types
    max_results: int = 100


@dataclass
class CollectResult:
    source: str
    offers: list[NormalizedOffer] = field(default_factory=list)
    rejected: int = 0  # enregistrements illisibles, ignorés un par un
    duplicates: int = 0  # même dedup_key renvoyée deux fois par la source
    error: CollectorError | None = None  # erreur qui a arrêté la source


class Collector(ABC):
    """Une source d'offres. Implémenter `fetch` (appel réseau) et `normalize` (pur, sans réseau)."""

    source: str  # identifiant stable de la source, conforme à SOURCE_PATTERN

    @abstractmethod
    def fetch(self, query: SearchQuery) -> Iterable[Mapping[str, Any]]:
        """Enregistrements bruts de la source. Lève une `CollectorError` typée en cas d'échec."""

    @abstractmethod
    def normalize(self, raw: Mapping[str, Any]) -> NormalizedOffer:
        """Convertit un enregistrement brut. Lève `InvalidResponse` s'il est inexploitable."""

    def collect(self, query: SearchQuery) -> CollectResult:
        """Récupère, normalise et dédoublonne. Un enregistrement illisible n'arrête pas la
        collecte ; une erreur de source l'arrête en gardant les offres déjà normalisées."""
        result, seen = CollectResult(source=self.source), set()
        try:
            for raw in self.fetch(query):
                try:
                    offer = self.normalize(raw)
                except (InvalidResponse, ValidationError, ValueError, KeyError, TypeError) as exc:
                    result.rejected += 1
                    # Type d'erreur seulement : le contenu de l'annonce ne va pas dans les journaux.
                    kind = type(exc).__name__
                    log.warning("collector=%s enregistrement rejeté (%s)", self.source, kind)
                    continue
                if query.contract_types and offer.contract_type not in query.contract_types:
                    continue
                if offer.dedup_key in seen:
                    result.duplicates += 1
                    continue
                seen.add(offer.dedup_key)
                result.offers.append(offer)
                if len(result.offers) >= query.max_results:
                    break
        except CollectorError as exc:
            result.error = exc
        # Bogue du connecteur : cette source s'arrête, les autres continuent (collect_all).
        except Exception as exc:  # noqa: BLE001
            result.error = CollectorError(self.source, f"erreur inattendue ({type(exc).__name__})")
        if result.error:
            kind = type(result.error).__name__
            log.error("collector=%s arrêté : %s (%s)", self.source, kind, result.error.message)
        return result


def collect_all(collectors: Iterable[Collector], query: SearchQuery) -> list[CollectResult]:
    """Lance chaque source ; une source en échec n'arrête pas les autres."""
    return [collector.collect(query) for collector in collectors]


def cross_source_duplicates(offers: Iterable[NormalizedOffer]) -> dict[str, list[NormalizedOffer]]:
    """Regroupe par empreinte les offres vues dans au moins deux sources différentes."""
    groups: dict[str, list[NormalizedOffer]] = {}
    for offer in offers:
        groups.setdefault(offer.fingerprint, []).append(offer)
    return {k: v for k, v in groups.items() if len({o.source for o in v}) > 1}
