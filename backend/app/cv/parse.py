"""Découpage du texte d'un CV en faits proposés, par règles locales (aucun appel réseau, aucune IA).

Le texte d'un CV est une donnée non fiable : il n'est jamais interprété comme une consigne, seulement
découpé en lignes. Les lignes d'identité (e-mail, téléphone, lien, adresse) et tout ce qui précède la
première rubrique (nom, coordonnées) sont écartés : ils n'entrent jamais dans un fait.
"""

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field

from app.ai.gateway.pseudonymize import ADDRESS, BIRTH, EMAIL, PHONE, URL

MAX_FACTS_PER_CV = 100
MAX_LINE = 300
SECTIONS = {
    "experience": r"exp[ée]riences?(?: professionnelles?)?|parcours professionnel|emplois?|stages?|work experience",
    "education": r"formations?|[ée]tudes|dipl[ôo]mes?|education|cursus",
    "skill": r"comp[ée]tences?(?: techniques?)?|skills|technologies|outils",
    "project": r"projets?(?: personnels?| acad[ée]miques?)?|projects",
    "language": r"langues?(?: et int[ée]r[êe]ts?)?|languages",
    "certification": r"certifications?|certificats?",
    "other": r"(?:centres? d.)?int[ée]r[êe]ts?|loisirs?|hobbies|activit[ée]s extra-?professionnelles?",
}
SECTION_RE = {kind: re.compile(rf"^(?:{pattern})\s*:?$", re.IGNORECASE) for kind, pattern in SECTIONS.items()}
TECHNOLOGIES = [
    "Python", "SQL", "PostgreSQL", "MySQL", "Pandas", "NumPy", "Scikit-learn", "TensorFlow", "PyTorch",
    "Spark", "Hadoop", "Airflow", "dbt", "Docker", "Kubernetes", "Git", "Linux", "Java", "JavaScript",
    "TypeScript", "React", "FastAPI", "Django", "Flask", "Power BI", "Tableau", "Excel", "R", "Scala",
    "MongoDB", "Kafka", "AWS", "Azure", "GCP", "Snowflake", "BigQuery", "LLM", "NLP",
]
TECH_RE = {t: re.compile(rf"(?<![\w+#.]){re.escape(t)}(?![\w+#])", re.IGNORECASE if len(t) > 2 else 0)
           for t in TECHNOLOGIES}
MONTHS = {"janv": 1, "jan": 1, "févr": 2, "fev": 2, "fév": 2, "mars": 3, "avr": 4, "mai": 5, "juin": 6,
          "juil": 7, "août": 8, "aout": 8, "sept": 9, "oct": 10, "nov": 11, "déc": 12, "dec": 12}
MONTH_NAME = r"(?:janv|jan|f[ée]vr|f[ée]v|mars|avr|mai|juin|juil|ao[uû]t|sept|oct|nov|d[ée]c)[a-zéû]*\.?"
POINT = rf"(?:(?:{MONTH_NAME}\s+|(?:0?[1-9]|1[0-2])/)?(?:19|20)\d\d)"
RANGE = re.compile(rf"\(?\b({POINT})\s*(?:[-–—]|à|a|au|to)\s*({POINT}|pr[ée]sent|aujourd.hui|en cours|actuel)\b\)?",
                   re.IGNORECASE)
SINCE = re.compile(rf"\b(?:depuis|since)\s+({POINT})\b", re.IGNORECASE)
SINGLE = re.compile(rf"\b({POINT})\b", re.IGNORECASE)
BULLET = re.compile(r"^[\s•·▪■◦*\-–—>]+")
IDENTITY = (EMAIL, PHONE, URL, ADDRESS, BIRTH)


@dataclass
class ProposedFact:
    kind: str
    text: str
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    technologies: list[str] = field(default_factory=list)


def _point(raw: str) -> dt.date | None:
    """« sept. 2022 », « 09/2021 » ou « 2023 » : le 1er du mois (janvier si seule l'année est connue)."""
    raw = raw.strip().lower().rstrip(".")
    year = re.search(r"(?:19|20)\d\d", raw)
    if not year:
        return None
    month = 1
    if (m := re.match(r"(\d{1,2})/", raw)):
        month = int(m.group(1))
    elif (m := re.match(r"[a-zéû]+", raw)):
        month = next((v for k, v in MONTHS.items() if m.group(0).startswith(k)), 1)
    try:
        return dt.date(int(year.group(0)), month, 1)
    except ValueError:
        return None


def _dates(line: str) -> tuple[str, dt.date | None, dt.date | None]:
    if (m := RANGE.search(line)):
        start, end = _point(m.group(1)), _point(m.group(2))  # « présent » -> None : en cours
        if start and end and end < start:
            start = end = None
        return (line[:m.start()] + line[m.end():]), start, end
    if (m := SINCE.search(line)):
        return (line[:m.start()] + line[m.end():]), _point(m.group(1)), None
    if (m := SINGLE.search(line)):
        return (line[:m.start()] + line[m.end():]), _point(m.group(1)), None
    return line, None, None


def _technologies(line: str) -> list[str]:
    return [t for t, pattern in TECH_RE.items() if pattern.search(line)][:30]


# Mots qui ne terminent jamais une phrase : la ligne suivante en est la suite (CV en colonnes étroites).
CONNECTORS = frozenset({"de", "des", "du", "d", "et", "en", "à", "a", "la", "le", "les", "l", "sur", "pour", "aux",
                        "au", "par", "avec", "ou", "un", "une", "dans", "chez", "of", "and", "for", "to"})
LAST_WORD = re.compile(r"(\w+)['’]?$")
MIN_HEADING_LETTERS = 5  # « SQL », « NLP », « AWS » sont des outils, pas des titres
OWN_LINE_HEADING_KINDS = (None, "skill", "language", "other")


def _is_caps_heading(line: str) -> bool:
    """Titre en majuscules (« LANGAGES », « TRANSVERSES ») : court, sans chiffre ni ponctuation, pas un outil."""
    heading = line.strip().strip("-–—_:=#• ").strip()
    letters = [c for c in heading if c.isalpha()]
    return (len(letters) >= MIN_HEADING_LETTERS and len(heading) <= 40 and heading.upper() == heading
            and not any(c.isdigit() or c in ",;()/|" for c in heading) and len(heading.split()) <= 4
            and not any(pattern.search(heading) for pattern in TECH_RE.values()))


def _continues(previous: str, raw: str) -> bool:
    """La ligne `raw` prolonge-t-elle la ligne `previous` (phrase coupée par la mise en page) ?"""
    line = raw.strip()
    if (not previous or BULLET.match(raw) or _section_of(line) or _is_caps_heading(line)
            or _section_of(previous) or _is_caps_heading(previous)):
        return False
    last = LAST_WORD.search(previous.lower())
    if last and last.group(1) in CONNECTORS:
        return True
    return line[0].islower() and previous[-1] not in ".!?:;"


def _logical_lines(cv_text: str) -> list[str]:
    out: list[str] = []
    for raw in cv_text.splitlines():
        line = raw.strip()[:MAX_LINE * 4]  # borne le travail des regex quelle que soit la ligne
        if not line:
            out.append("")
        elif out and out[-1] and _continues(out[-1], raw[:MAX_LINE * 4]):
            out[-1] = f"{out[-1]} {line}"[:MAX_LINE * 4]
        else:
            out.append(line)
    return out


def _section_of(line: str) -> str | None:
    heading = line.strip().strip("-–—_:=# ").strip()
    if not heading or len(heading) > 40:
        return None
    return next((kind for kind, pattern in SECTION_RE.items() if pattern.match(heading)), None)


CONTROL = re.compile("[\0--  ]")


def _tidy(line: str) -> str:
    line = BULLET.sub("", CONTROL.sub(" ", line))
    line = line.strip(" 	|,;:–—-")  # strip est linéaire (une regex finale serait quadratique sur des espaces)
    return re.sub(r"\s+", " ", line).strip()


def _norm(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.replace("’", "'"))
    return re.sub(r"[^a-z0-9+#]+", " ", "".join(c for c in plain if not unicodedata.combining(c)).lower()).strip()


MIN_CONTAINED = 25  # un fait long déjà contenu dans un fait connu (ou l'inverse) est le même fait


def drop_known(facts: list[ProposedFact], known: list[tuple[str, str]]) -> list[ProposedFact]:
    """Écarte les faits déjà connus (validés ou proposés), à la casse, aux accents et à la ponctuation près."""
    seen = [(kind, _norm(text)) for kind, text in known]
    kept = []
    for fact in facts:
        norm = _norm(fact.text)
        if not norm or any(kind == fact.kind and (
                norm == other or (min(len(norm), len(other)) >= MIN_CONTAINED and (norm in other or other in norm)))
                for kind, other in seen):
            continue
        seen.append((fact.kind, norm))
        kept.append(fact)
    return kept


def propose_facts(cv_text: str) -> list[ProposedFact]:
    facts: list[ProposedFact] = []
    kind: str | None = None  # rien n'est retenu avant la première rubrique : c'est l'en-tête d'identité
    for line in _logical_lines(cv_text):
        if not line:
            continue
        if (section := _section_of(line)) is not None:
            kind = section
            continue
        if kind in OWN_LINE_HEADING_KINDS and _is_caps_heading(line):
            continue  # sous-titre de colonne : jamais un fait
        if kind is None or any(p.search(line) for p in IDENTITY):
            continue
        rest, start, end = _dates(line)
        rest = _tidy(rest)
        if kind in ("skill", "language"):
            for item in re.split(r"[,;•·|]|\s{3,}", rest):
                item = _tidy(item.split(":", 1)[-1] if kind == "skill" and ":" in item else item)
                if 1 <= len(item) <= 80:
                    facts.append(ProposedFact(kind, item[:MAX_LINE], technologies=_technologies(item)))
        elif len(rest) >= 6:
            previous = facts[-1] if facts else None
            if (previous and previous.kind == kind and previous.start_date and not (start or end)
                    and len(previous.text) + len(rest) < 900):  # ligne de détail sous un poste daté
                previous.text += f" ; {rest[:MAX_LINE]}"
                previous.technologies = list(dict.fromkeys([*previous.technologies, *_technologies(line)]))[:30]
                continue
            facts.append(ProposedFact(kind, rest[:MAX_LINE], start, end, _technologies(line)))
        if len(facts) >= MAX_FACTS_PER_CV:
            break
    seen, unique = set(), []
    for fact in facts:  # un même fait écrit deux fois n'est proposé qu'une fois
        key = (fact.kind, fact.text.lower())
        if key not in seen:
            seen.add(key)
            unique.append(fact)
    return unique[:MAX_FACTS_PER_CV]
