"""Filtres durs : du code, jamais d'IA. Chaque contrôle rend « ok », « échec » ou « inconnu ».

Une information absente de l'offre donne « inconnu » : elle n'écarte jamais l'offre. Selon la
politique (`MatchPolicy`), un échec écarte l'offre (HARD), plafonne son score plus tard (MANDATORY,
issue #18) ou ne fait que baisser une note (DESIRED). Les raisons sont des phrases lisibles.
"""

import datetime as dt
import json
import math
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import Connection, text

EDUCATION_RANK = {"bac": 0, "bac_plus_2": 1, "bac_plus_3": 2, "bac_plus_4": 3, "bac_plus_5": 4, "doctorate": 5}
START_TOLERANCE = dt.timedelta(days=30)  # une offre qui commence un peu avant la date voulue passe


class Status(StrEnum):
    OK = "ok"
    FAIL = "fail"
    UNKNOWN = "unknown"


class Level(StrEnum):
    HARD = "hard"  # écarte l'offre
    MANDATORY = "mandatory"  # plafonne le score (#18)
    DESIRED = "desired"  # souhaité : ne fait que baisser la note de la composante


DEFAULT_LEVELS: Mapping[str, Level] = {
    "expired": Level.HARD, "excluded_keywords": Level.HARD, "contract": Level.HARD,
    "location": Level.MANDATORY, "education": Level.MANDATORY,
    "start_date": Level.DESIRED, "salary": Level.DESIRED,
}


@dataclass(frozen=True)
class MatchPolicy:
    """Quels critères sont durs, obligatoires ou souhaités. Un réglage par utilisateur demanderait
    une colonne de plus dans `search_preferences` : pour l'instant la politique est celle-ci."""

    levels: Mapping[str, Level] = field(default_factory=lambda: dict(DEFAULT_LEVELS))

    def level(self, name: str) -> Level:
        return self.levels.get(name, Level.DESIRED)


@dataclass(frozen=True)
class OfferView:
    """Ce que les filtres savent d'une offre : colonnes de `job_postings`, plus l'extraction (#16)
    quand elle existe. Tout champ peut être absent."""

    title: str
    description: str = ""
    location: str | None = None
    expired: bool = False
    contract_type: str | None = None  # mêmes valeurs que `search_preferences.contract_types`
    start_date: dt.date | None = None
    valid_until: dt.date | None = None
    education_level: str | None = None  # niveau minimal demandé
    remote: bool | None = None
    salary_eur: int | None = None  # brut annuel


@dataclass(frozen=True)
class Criteria:
    """Lecture de `search_preferences`."""

    locations: tuple[tuple[str, int], ...] = ()  # (libellé, rayon en km)
    remote_accepted: bool = False
    contract_types: tuple[str, ...] = ()
    start_date: dt.date | None = None
    education_level: str | None = None
    min_salary_eur: int | None = None
    excluded_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    reason: str = ""


@dataclass(frozen=True)
class FilterOutcome:
    checks: tuple[Check, ...]
    discarded: bool
    reasons: tuple[str, ...]  # raisons de l'écart (échecs HARD)
    violated_mandatory: tuple[str, ...]  # noms des critères MANDATORY en échec, pour le plafond (#18)


def normalize(value: str) -> str:
    """Minuscules sans accents ni ponctuation : « Île-de-France » == « ile de france »."""
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    letters = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", letters).strip()


def _contains_word(haystack: str, needle: str) -> bool:
    return bool(needle) and re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


Geocoder = Callable[[str], tuple[float, float] | None]


def check_expired(offer: OfferView, today: dt.date) -> Check:
    if offer.expired or (offer.valid_until is not None and offer.valid_until < today):
        return Check("expired", Status.FAIL, "L'offre est expirée.")
    return Check("expired", Status.OK)


def check_excluded_keywords(offer: OfferView, criteria: Criteria) -> Check:
    haystack = normalize(f"{offer.title} {offer.description}")
    found = [word for word in criteria.excluded_keywords if _contains_word(haystack, normalize(word))]
    if found:
        return Check("excluded_keywords", Status.FAIL, f"Mot exclu présent dans l'offre : {', '.join(found)}.")
    return Check("excluded_keywords", Status.OK)


def check_contract(offer: OfferView, criteria: Criteria) -> Check:
    if not criteria.contract_types:
        return Check("contract", Status.OK)
    if offer.contract_type is None:
        return Check("contract", Status.UNKNOWN)
    if offer.contract_type in criteria.contract_types:
        return Check("contract", Status.OK)
    return Check("contract", Status.FAIL, f"Type de contrat non voulu : {offer.contract_type}.")


def check_location(offer: OfferView, criteria: Criteria, geocode: Geocoder | None = None) -> Check:
    """Le rayon n'est évalué que si `geocode` donne des coordonnées pour l'offre et pour la zone ;
    sinon on compare les noms de lieux (la zone contient le lieu de l'offre ou l'inverse)."""
    if offer.remote and criteria.remote_accepted:
        return Check("location", Status.OK)
    if not criteria.locations:
        return Check("location", Status.OK)
    if not offer.location:
        return Check("location", Status.UNKNOWN)
    place = normalize(offer.location)
    known = False
    for label, radius in criteria.locations:
        wanted = normalize(label)
        if wanted and (_contains_word(place, wanted) or _contains_word(wanted, place)):
            return Check("location", Status.OK)
        if geocode is not None:
            here, there = geocode(offer.location), geocode(label)
            if here and there:
                known = True
                if _haversine_km(here, there) <= radius:
                    return Check("location", Status.OK)
    if not known:
        return Check("location", Status.UNKNOWN)  # sans coordonnées, impossible d'affirmer que c'est loin
    return Check("location", Status.FAIL, f"Lieu hors de la zone voulue : {offer.location}.")


def check_start_date(offer: OfferView, criteria: Criteria) -> Check:
    if criteria.start_date is None:
        return Check("start_date", Status.OK)
    if offer.start_date is None:
        return Check("start_date", Status.UNKNOWN)
    if offer.start_date + START_TOLERANCE < criteria.start_date:
        return Check("start_date", Status.FAIL, f"L'offre commence trop tôt ({offer.start_date.isoformat()}).")
    return Check("start_date", Status.OK)


def check_education(offer: OfferView, criteria: Criteria) -> Check:
    wanted = EDUCATION_RANK.get(offer.education_level or "")
    mine = EDUCATION_RANK.get(criteria.education_level or "")
    if wanted is None or mine is None:
        return Check("education", Status.UNKNOWN)
    if wanted > mine:
        return Check("education", Status.FAIL, f"Niveau d'études demandé trop élevé : {offer.education_level}.")
    return Check("education", Status.OK)


def check_salary(offer: OfferView, criteria: Criteria) -> Check:
    if criteria.min_salary_eur is None:
        return Check("salary", Status.OK)
    if offer.salary_eur is None:
        return Check("salary", Status.UNKNOWN)
    if offer.salary_eur < criteria.min_salary_eur:
        return Check("salary", Status.FAIL, f"Salaire sous le minimum voulu ({offer.salary_eur} €).")
    return Check("salary", Status.OK)


def apply_filters(offer: OfferView, criteria: Criteria, policy: MatchPolicy | None = None, *,
                  today: dt.date | None = None, geocode: Geocoder | None = None) -> FilterOutcome:
    policy = policy or MatchPolicy()
    checks = (check_expired(offer, today or dt.date.today()), check_excluded_keywords(offer, criteria),
              check_contract(offer, criteria), check_location(offer, criteria, geocode),
              check_start_date(offer, criteria), check_education(offer, criteria), check_salary(offer, criteria))
    failed = [c for c in checks if c.status is Status.FAIL]
    hard = tuple(c.reason for c in failed if policy.level(c.name) is Level.HARD)
    mandatory = tuple(c.name for c in failed if policy.level(c.name) is Level.MANDATORY)
    return FilterOutcome(checks, discarded=bool(hard), reasons=hard, violated_mandatory=mandatory)


def load_criteria(conn: Connection) -> Criteria | None:
    """Critères de l'utilisateur de la transaction (RLS) ; None s'il n'en a pas encore saisi."""
    row = conn.execute(text(
        "SELECT locations, remote_accepted, contract_types, start_date, education_level, min_salary_eur, "
        "excluded_keywords FROM search_preferences")).mappings().first()
    if row is None:
        return None
    return Criteria(
        locations=tuple((loc["label"], loc["radius_km"]) for loc in row["locations"]),
        remote_accepted=row["remote_accepted"], contract_types=tuple(row["contract_types"]),
        start_date=row["start_date"], education_level=row["education_level"],
        min_salary_eur=row["min_salary_eur"], excluded_keywords=tuple(row["excluded_keywords"]))


def record_discard(conn: Connection, user_id: str, posting_id: str, outcome: FilterOutcome) -> None:
    """Enregistre l'écart : un score à 0 dont `blocking_reasons` porte les raisons (visible dans
    GET /offers/{id}). Un score écrit plus tard remplace celui-ci (le plus récent gagne)."""
    conn.execute(text(
        "INSERT INTO scores (user_id, job_posting_id, value, confidence, explanation, blocking_reasons) "
        "VALUES (:uid, :posting, 0, 'high', :explanation, CAST(:reasons AS jsonb))"),
        {"uid": user_id, "posting": posting_id, "explanation": "Offre écartée par un filtre dur.",
         "reasons": json.dumps(list(outcome.reasons), ensure_ascii=False)})
