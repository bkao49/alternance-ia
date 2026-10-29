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

from pydantic import BaseModel, ConfigDict, Field, field_validator

log = logging.getLogger(__name__)

SOURCE_PATTERN = r"^[a-z][a-z0-9_]{1,39}$"
# Paramètres de suivi retirés de l'URL canonique (ils changent d'une diffusion à l'autre).
TRACKING_PARAMS = re.compile(r"^(utm_.*|gclid|fbclid|mc_[a-z]+|xtor)$", re.IGNORECASE)
MAX_RESULTS = 1000
MAX_URL, MAX_DESCRIPTION = 2000, 50_000
HOST_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")
DEFAULT_PORTS = {"http": 80, "https": 443}
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
    """Erreur d'une source. `retryable` dit si l'orchestrateur peut réessayer plus tard.

    `message` est un texte fixe écrit par le développeur (« HTTP 403 », « quota journalier ») :
    jamais le corps d'une réponse ni le texte d'une annonce.
    """

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


def _is_hidden(char: str) -> bool:
    """Contrôles (C0, C1) sauf tabulation et retours à la ligne, et caractères de format
    (bidi U+202E, zéro-largeur U+200B…) qui peuvent falsifier l'affichage d'un titre."""
    return char not in "\t\n\r" and unicodedata.category(char) in ("Cc", "Cf")


def clean_text(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFC", value) if not _is_hidden(c)).strip()


def canonical_url(url: str) -> str:
    """http(s) seulement, hôte validé (IDNA), port par défaut retiré, sans identifiants,
    fragment ni paramètres de suivi."""
    url = url.strip()
    if any(_is_hidden(c) or c.isspace() for c in url):
        raise ValueError("caractère interdit dans l'URL")
    parts = urlsplit(url)
    scheme, host = parts.scheme.lower(), parts.hostname or ""
    if scheme not in DEFAULT_PORTS or not host:
        raise ValueError("URL http(s) attendue")
    if ":" in host:  # IPv6 : urlsplit retire les crochets
        host = f"[{host}]"
    else:
        host = host.encode("idna").decode("ascii")  # « exämple.fr » → « xn--exmple-cua.fr »
        if not HOST_PATTERN.match(host):
            raise ValueError("hôte invalide")
    port = parts.port  # lève ValueError hors de 0-65535
    if port == 0:
        raise ValueError("port invalide")
    netloc = host + (f":{port}" if port and port != DEFAULT_PORTS[scheme] else "")
    params = parse_qsl(parts.query, keep_blank_values=True)
    query = urlencode(sorted((k, v) for k, v in params if not TRACKING_PARAMS.match(k)))
    canonical = urlunsplit((scheme, netloc, parts.path or "/", query, ""))
    if len(canonical) > MAX_URL:
        raise ValueError("URL trop longue")
    return canonical


def _fold(value: str | None) -> str:
    """Minuscules, sans accents ni ponctuation : « Développeur·se  IA » → « developpeur se ia »."""
    if not value:
        return ""
    value = value.replace("œ", "oe").replace("Œ", "oe").replace("æ", "ae").replace("Æ", "ae")
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text.lower()).split())


def _sha256(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


class NormalizedOffer(BaseModel):
    """Une offre, quelle que soit sa source. Correspond aux colonnes de `job_postings`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str = Field(pattern=SOURCE_PATTERN)
    external_id: str = Field(min_length=1, max_length=200)
    url: str  # longueur vérifiée après mise en forme canonique
    title: str = Field(min_length=1, max_length=300)
    company: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    contract_type: ContractType
    description_text: str = ""  # tronquée à MAX_DESCRIPTION plutôt que rejetée
    published_at: dt.datetime | None = None

    @field_validator("external_id", "title", "company", mode="before")
    @classmethod
    def _clean(cls, value: Any) -> Any:
        return clean_text(value) if isinstance(value, str) else value

    @field_validator("description_text", mode="before")
    @classmethod
    def _clean_description(cls, value: Any) -> Any:
        return clean_text(value)[:MAX_DESCRIPTION] if isinstance(value, str) else value

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
        """Doublon entre sources : mêmes titre, entreprise, lieu et type de contrat, repliés.
        Titre non latin (repli vide) : empreinte propre à l'offre, pour ne rien fusionner à tort."""
        if not _fold(self.title):
            return _sha256("unique", self.source, self.external_id)
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

    def __post_init__(self) -> None:
        if not 1 <= self.max_results <= MAX_RESULTS:
            raise ValueError(f"max_results doit être entre 1 et {MAX_RESULTS}")


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
        """Enregistrements bruts de la source. Lève une `CollectorError` typée en cas d'échec.

        Doit être un générateur paresseux (page par page) : `collect` cesse de le lire dès
        `query.max_results` atteint ; les filtres de `query` sont transmis à la source quand
        elle les accepte, pour ne pas consommer de quota inutilement."""

    @abstractmethod
    def normalize(self, raw: Mapping[str, Any]) -> NormalizedOffer:
        """Convertit un enregistrement brut. Lève `InvalidResponse` s'il est inexploitable."""

    def collect(self, query: SearchQuery) -> CollectResult:
        """Récupère, normalise et dédoublonne. Un enregistrement illisible n'arrête pas la
        collecte ; une erreur de source l'arrête en gardant les offres déjà normalisées."""
        source = getattr(self, "source", None)
        result, seen = CollectResult(source=str(source)), set()
        if not isinstance(source, str) or not re.fullmatch(SOURCE_PATTERN, source):
            result.error = CollectorError(str(source), "identifiant de source invalide")
            log.error("collector=%r arrêté : identifiant de source invalide", source)
            return result
        try:
            for raw in self.fetch(query):
                try:
                    offer = self.normalize(raw)
                except CollectorError as exc:
                    if not isinstance(exc, InvalidResponse):
                        raise
                    self._reject(exc)
                    result.rejected += 1
                    continue
                # Enregistrement inattendu (ValidationError, KeyError, bogue…) : ignoré seul.
                except Exception as exc:  # noqa: BLE001
                    self._reject(exc)
                    result.rejected += 1
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
            result.error = CollectorError(source, f"erreur inattendue ({type(exc).__name__})")
            result.error.__cause__ = exc  # trace d'origine conservée pour le débogage
        if result.error:
            # Type seulement : rien de la réponse ni de l'annonce ne va dans les journaux.
            log.error("collector=%s arrêté (%s)", source, type(result.error).__name__)
        return result

    def _reject(self, exc: Exception) -> None:
        # Pas de trace : une ValidationError contient les valeurs de l'annonce.
        log.warning("collector=%s enregistrement rejeté (%s)", self.source, type(exc).__name__)


def collect_all(collectors: Iterable[Collector], query: SearchQuery) -> list[CollectResult]:
    """Lance chaque source ; une source en échec n'arrête pas les autres."""
    results = []
    for collector in collectors:
        try:
            results.append(collector.collect(query))
        except Exception as exc:  # noqa: BLE001 (filet de sécurité si `collect` est surchargée)
            name = str(getattr(collector, "source", type(collector).__name__))
            error = CollectorError(name, f"erreur inattendue ({type(exc).__name__})")
            error.__cause__ = exc
            log.error("collector=%s arrêté (%s)", name, type(exc).__name__)
            results.append(CollectResult(source=name, error=error))
    return results


def cross_source_duplicates(offers: Iterable[NormalizedOffer]) -> dict[str, list[NormalizedOffer]]:
    """Regroupe par empreinte les offres vues dans au moins deux sources différentes."""
    groups: dict[str, list[NormalizedOffer]] = {}
    for offer in offers:
        groups.setdefault(offer.fingerprint, []).append(offer)
    return {k: v for k, v in groups.items() if len({o.source for o in v}) > 1}
