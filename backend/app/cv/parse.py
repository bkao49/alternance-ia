"""Découpage du texte d'un CV en faits proposés, par règles locales (aucun appel réseau, aucune IA).

Le texte d'un CV est une donnée non fiable : il n'est jamais interprété comme une consigne, seulement
découpé en lignes. Les lignes d'identité (e-mail, téléphone, lien, adresse) et tout ce qui précède la
première rubrique (nom, coordonnées) sont écartés : ils n'entrent jamais dans un fait.
"""

import datetime as dt
import re
from dataclasses import dataclass, field

from app.ai.gateway.pseudonymize import ADDRESS, BIRTH, EMAIL, PHONE, URL

MAX_FACTS_PER_CV = 100
MAX_LINE = 300
SECTIONS = {
    "experience": r"exp[ée]riences?(?: professionnelles?)?|parcours professionnel|emplois?|stages?|work experience",
    "education": r"formations?|[ée]tudes|dipl[ôo]mes?|education|cursus",
    "skill": r"comp[ée]tences?(?: techniques?)?|skills|technologies|outils",
    "project": r"projets?(?: personnels?| acad[ée]miques?)?|projects",
    "language": r"langues?|languages",
    "certification": r"certifications?|certificats?",
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


def propose_facts(cv_text: str) -> list[ProposedFact]:
    facts: list[ProposedFact] = []
    kind: str | None = None  # rien n'est retenu avant la première rubrique : c'est l'en-tête d'identité
    for raw in cv_text.splitlines():
        line = raw.strip()[:MAX_LINE * 4]  # borne le travail des regex quelle que soit la ligne
        if not line:
            continue
        if (section := _section_of(line)) is not None:
            kind = section
            continue
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
