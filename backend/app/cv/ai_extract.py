"""Extraction structurée des faits d'un CV par l'IA, via la passerelle `ai/gateway` (jamais en direct).

Le texte du CV est pseudonymisé par la passerelle (e-mail, téléphone, adresse, nom) avant de partir.
La réponse du modèle est une donnée non fiable : JSON validé, puis chaque fait doit être **ancré dans le
texte du CV** (ses mots et ses années y figurent). Ce qui n'y est pas est écarté : le modèle reformate,
il n'invente rien. Tous les faits restent « proposés » jusqu'à la validation de l'utilisateur.
En cas d'échec (IA absente, plafond atteint, réponse illisible), l'appelant retombe sur `parse.py`.
"""

import datetime as dt
import json
import logging
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.ai.gateway import DataKind, GatewayError, LLMGateway
from app.cv.parse import MAX_FACTS_PER_CV, MAX_LINE, ProposedFact

log = logging.getLogger("app.cv")

MAX_CV_CHARS = 30_000
MIN_GROUNDED = 0.85  # part des mots d'un fait qui doivent figurer dans le CV
INSTRUCTIONS = """Tu extrais les faits d'un CV pour un profil professionnel. Le CV peut venir d'une mise en page en
deux colonnes : les lignes peuvent être coupées ou mélangées, recolle les phrases coupées.
Règles :
- Un fait = une expérience, une formation, un projet, une compétence, une certification, une langue ou un
  centre d'intérêt. Une phrase complète par fait, recopiée ou à peine reformulée.
- N'invente rien : ni date, ni chiffre, ni outil, ni employeur. N'ajoute rien qui ne soit écrit dans le CV.
- Ignore les titres de rubrique et de colonne (LANGAGES, CONCEPTION, COMPÉTENCES…) : ce ne sont pas des faits.
- Ignore l'identité et les coordonnées (nom, e-mail, téléphone, adresse, liens).
- Ne mélange pas deux rubriques dans un même fait. Une compétence par fait (« Python », « SQL »).
- Dates au format AAAA-MM (ou AAAA) ; null si inconnues ; end_date null si en cours.
Réponds par UN SEUL objet JSON, sans texte autour :
{"facts": [{"kind": "experience|education|project|skill|certification|language|other", "text": "…",
"start_date": "AAAA-MM"|null, "end_date": "AAAA-MM"|null, "technologies": ["Python"]}]}"""
FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class _Fact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: Literal["experience", "education", "project", "skill", "certification", "language", "other"]
    text: str = Field(min_length=2, max_length=1000)
    start_date: str | None = None
    end_date: str | None = None
    technologies: list[str] = Field(default_factory=list, max_length=30)


class _Reply(BaseModel):
    model_config = ConfigDict(extra="ignore")

    facts: list[_Fact] = Field(max_length=300)


def _fold(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.replace("’", "'"))
    return "".join(c for c in plain if not unicodedata.combining(c)).lower()


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9+#]+", _fold(text))


def _date(raw: str | None, cv_years: set[str]) -> dt.date | None:
    """« 2024-09 » ou « 2024 » ; refusée si l'année n'est pas écrite dans le CV."""
    if not raw or not (m := re.fullmatch(r"((?:19|20)\d\d)(?:-(\d{1,2}))?", raw.strip())):
        return None
    month = int(m.group(2) or 1)
    if m.group(1) not in cv_years or not 1 <= month <= 12:
        return None
    return dt.date(int(m.group(1)), month, 1)


def _grounded(text: str, cv_words: set[str]) -> bool:
    words = _words(text)
    return bool(words) and sum(w in cv_words for w in words) / len(words) >= MIN_GROUNDED


def _line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip(" \t|,;:–—-")


def parse_reply(reply: str, cv_text: str) -> list[ProposedFact]:
    """Valide la réponse du modèle ; lève ValueError si elle est inutilisable."""
    try:
        parsed = _Reply.model_validate(json.loads(FENCE.sub("", reply.strip())))
    except (ValidationError, json.JSONDecodeError, TypeError) as failure:
        raise ValueError("réponse non conforme") from failure
    cv_words = set(_words(cv_text))
    cv_years = set(re.findall(r"(?:19|20)\d\d", cv_text))
    facts: list[ProposedFact] = []
    for item in parsed.facts:
        text = _line(item.text)[:MAX_LINE]
        if len(text) < 2 or not _grounded(text, cv_words):
            continue  # inventé ou trop éloigné du CV
        start, end = _date(item.start_date, cv_years), _date(item.end_date, cv_years)
        if start and end and end < start:
            start = end = None
        tech = [t.strip()[:60] for t in item.technologies if t.strip() and _grounded(t, cv_words)]
        facts.append(ProposedFact(item.kind, text, start, end, list(dict.fromkeys(tech))))
    if not facts:
        raise ValueError("aucun fait exploitable")
    return facts[:MAX_FACTS_PER_CV]


def _known_name(cv_text: str) -> list[str]:
    """Le nom figure presque toujours à la première ligne : la passerelle le remplace avant l'envoi."""
    first = next((line.strip() for line in cv_text.splitlines() if line.strip()), "")
    return [first] if 3 <= len(first) <= 60 and 2 <= len(first.split()) <= 4 and not any(c.isdigit() for c in first) else []


def extract_with_ai(gateway: LLMGateway, user_id: str, cv_text: str) -> list[ProposedFact] | None:
    """Faits proposés par l'IA, ou None si elle ne peut pas répondre (l'appelant utilise alors les règles)."""
    try:
        reply = gateway.call(user_id, purpose="cv_extract", kind=DataKind.PROFILE, instructions=INSTRUCTIONS,
                             data=cv_text[:MAX_CV_CHARS], known_names=_known_name(cv_text), max_output_tokens=4000,
                             use_cache=False)  # une réponse inutilisable ne doit pas rester en cache
        return parse_reply(reply.text, cv_text)
    except GatewayError as failure:
        log.warning("extraction du CV par l'IA indisponible (%s)", failure.code)
    except ValueError:
        log.warning("extraction du CV par l'IA inutilisable")
    return None
