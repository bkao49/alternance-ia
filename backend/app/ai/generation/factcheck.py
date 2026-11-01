"""Contrôle factuel déterministe d'un texte généré (CV ou lettre). Aucun modèle de langage ici.

Chaque ligne doit citer au moins un fait **validé** de l'utilisateur, et tout ce qui est vérifiable dans
la ligne doit exister dans les faits cités : nombres (chiffres ou en lettres), dates (année, mois, couples
mois-année), noms propres et sigles (employeurs, écoles, outils), technologies connues, diplômes. Ce qui
n'est pas justifié est rejeté avec sa raison. Le contrôle est volontairement strict : une reformulation
qui change un chiffre ou ajoute un nom est refusée, l'utilisateur la corrige ou cite le bon fait.
Limite connue : la première lettre majuscule d'une ligne peut cacher un nom d'entreprise ; elle n'est
tolérée que si le mot ressemble à un verbe ou à un nom d'action (suffixes) et n'est le nom d'aucun autre fait.
"""

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from app.ai.generation.schema import Fact, Section

MONTHS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
          "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}
MONTH_ABBREVIATIONS = {"janv": 1, "fevr": 2, "avr": 4, "juil": 7, "sept": 9, "oct": 10, "nov": 11, "dec": 12}
NUMBER_WORDS = {"deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9,
                "dix": 10, "onze": 11, "douze": 12, "quinze": 15, "vingt": 20, "trente": 30, "quarante": 40,
                "cinquante": 50, "soixante": 60, "cent": 100, "mille": 1000}
TECHNOLOGIES = frozenset(["python", "sql", "nosql", "postgresql", "postgres", "mysql", "sqlite", "mongodb", "redis", "oracle", "spark", "pyspark", "hadoop", "kafka", "airflow", "dbt", "docker", "kubernetes", "git", "github", "gitlab", "linux", "bash", "aws", "azure", "gcp", "tableau", "powerbi", "excel", "pandas", "numpy", "scipy", "sklearn", "scikit-learn", "tensorflow", "pytorch", "keras", "xgboost", "lightgbm", "java", "javascript", "typescript", "scala", "rust", "golang", "php", "matlab", "sas", "snowflake", "bigquery", "redshift", "databricks", "jenkins", "terraform", "ansible", "fastapi", "flask", "django", "react", "angular", "vue", "node", "opencv", "nltk", "spacy", "huggingface", "langchain", "mlflow", "streamlit", "plotly", "matplotlib", "seaborn", "jupyter", "hive", "elasticsearch", "cassandra", "neo4j", "grafana", "prometheus", "looker", "qlik", "talend", "nifi", "pytest", "html", "css"])
DEGREES = re.compile(r"\b(licence|master|bts|dut|mba|doctorat|phd|bachelor|bac\s*\+\s*\d)\b")
CUE = re.compile(r"\bchez\s+(?:(?:le|la|les|l|un|une|de|du|des|d)\b\s*)*([^\W\d_][\w+#-]*)")
INITIAL_WORDS = frozenset({
    "je", "j", "nous", "il", "elle", "mon", "ma", "mes", "notre", "nos", "le", "la", "les",
    "un", "une", "des", "du", "de", "d", "l", "dans", "en", "au", "aux", "pour", "avec", "sur",
    "par", "et", "ou", "ce", "cette", "ces", "ainsi", "depuis", "lors", "apres", "avant", "sans",
    "sous", "chez", "comme", "aussi", "tres", "plus",
})
INITIAL_VERB_LIKE = re.compile(r"(é|ée|és|ées|u|ue|ues|us|it|er|ir|ant|ion|ions|ment|ments|age|ages|eur|ance|ence)$")
WORD = re.compile(r"[^\W\d_][\w+#]*(?:[-.][\w+#]+)*")
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
PAIR_NAMED = re.compile(r"\b([a-z]{3,9})\.?\s+(\d{4})\b")
PAIR_NUMERIC = re.compile(r"\b(\d{1,2})\s*[/.-]\s*(\d{4})\b|\b(\d{4})\s*-\s*(\d{2})\b")
THOUSANDS = re.compile(r"(?<=\d)[   ](?=\d{3}\b)")


def fold(text: str) -> str:
    """Minuscules, sans accents, apostrophes droites, espaces fines de milliers rassemblés."""
    plain = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text).replace("’", "'"))
    return THOUSANDS.sub("", "".join(c for c in plain if not unicodedata.combining(c)).lower())


def _month(word: str) -> int | None:
    return MONTHS.get(word) or MONTH_ABBREVIATIONS.get(word)


def _numbers(folded: str) -> set[str]:
    folded = PAIR_NAMED.sub(lambda m: m.group(2) if _month(m.group(1)) else m.group(0), folded)  # « sept. 2024 » n'est pas 7
    found = {_number(n) for n in NUMBER.findall(folded)}
    found |= {str(NUMBER_WORDS[w]) for w in re.findall(r"[a-z]+", folded) if w in NUMBER_WORDS}
    return found


def _number(raw: str) -> str:
    """« 05 » → « 5 », « 1,50 » → « 1.5 »."""
    value = format(Decimal(raw.replace(",", ".")), "f")
    return value.rstrip("0").rstrip(".") if "." in value else value


def _pairs(folded: str) -> set[tuple[int, int]]:
    pairs = {(int(y), m) for w, y in PAIR_NAMED.findall(folded) if (m := _month(w))}
    for a, b, c, d in PAIR_NUMERIC.findall(folded):
        month, year = (int(a), int(b)) if a else (int(d), int(c))
        if 1 <= month <= 12:
            pairs.add((year, month))
    return pairs


def _months(folded: str) -> set[int]:
    return {MONTHS[w] for w in re.findall(r"[a-z]+", folded) if w in MONTHS}


@dataclass(frozen=True)
class Issue:
    section: int
    bullet: int
    code: str
    message: str  # en français, pour l'utilisateur


@dataclass(frozen=True)
class CheckResult:
    issues: tuple[Issue, ...]

    @property
    def ok(self) -> bool:
        return not self.issues


class _Evidence:
    """Ce que les faits cités permettent d'affirmer."""

    def __init__(self, facts: Iterable[Fact], extra_names: Iterable[str]):
        folded = fold(" ".join(f"{f.text} {f.source or ''} {' '.join(f.technologies)}" for f in facts))
        dates = [d for f in facts for d in (f.start_date, f.end_date) if d]
        self.text = folded
        self.words = set(re.findall(r"[a-z0-9]+", folded))
        self.technologies = {fold(t) for f in facts for t in f.technologies}
        self.numbers = _numbers(folded) | {str(n) for d in dates for n in (d.year, d.month, d.day)}
        self.months = _months(folded) | {d.month for d in dates}
        self.pairs = _pairs(folded) | {(d.year, d.month) for d in dates}
        self.names = set(re.findall(r"[a-z0-9]+", fold(" ".join(extra_names))))

    def has_word(self, word: str) -> bool:
        parts = re.findall(r"[a-z0-9]+", word)
        return word in self.technologies or all(p in self.words for p in parts)


def _check_line(line: str, evidence: _Evidence, lexicon: frozenset[str], other_words: set[str]) -> list[tuple[str, str]]:
    problems = []
    folded = fold(line)
    for number in sorted(_numbers(folded) - evidence.numbers):
        problems.append(("number_not_in_facts", f"Le nombre « {number} » n'apparaît dans aucun fait cité."))
    for year, month in sorted(_pairs(folded) - evidence.pairs):
        problems.append(("date_not_in_facts", f"La date « {month:02d}/{year} » ne correspond à aucun fait cité."))
    for month in sorted(_months(folded) - evidence.months):
        problems.append(("date_not_in_facts", f"Le mois n° {month} ne correspond à aucun fait cité."))
    for degree in sorted({re.sub(r"\s", "", d) for d in DEGREES.findall(folded)}):
        if not any(re.sub(r"\s", "", d) == degree for d in DEGREES.findall(evidence.text)):
            problems.append(("degree_not_in_facts", f"Le diplôme « {degree} » n'apparaît dans aucun fait cité."))
    for index, match in enumerate(WORD.finditer(line)):
        word, low = match.group(0), fold(match.group(0))
        upper = [c for c in word if c.isalpha()]
        is_acronym = len(upper) >= 2 and word.isupper()
        is_camel = any(c.isupper() for c in word[1:]) and not word.isupper()
        before = line[:match.start()].rstrip()
        initial = not before or before[-1] in ".!?:;"
        if low in lexicon and not evidence.has_word(low):
            problems.append(("technology_not_in_facts", f"La technologie « {word} » n'apparaît dans aucun fait cité."))
        elif is_acronym or is_camel or (word[0].isupper() and not initial):
            if not evidence.has_word(low) and not set(re.findall(r"[a-z0-9]+", low)) <= evidence.names:
                problems.append(("name_not_in_facts", f"Le nom « {word} » n'apparaît dans aucun fait cité."))
        elif word[0].isupper() and initial and not is_acronym:
            if low in INITIAL_WORDS:
                continue
            if not evidence.has_word(low) and (low in other_words or not INITIAL_VERB_LIKE.search(word.lower())):
                problems.append(("name_not_in_facts", f"Le mot « {word} » en début de ligne ressemble à un nom "
                                 + "absent des faits cités."))
    for match in CUE.finditer(folded):
        if not evidence.has_word(match.group(1)) and match.group(1) not in evidence.names:
            problems.append(("name_not_in_facts", f"L'employeur « {match.group(1)} » n'apparaît dans aucun fait cité."))
    seen = set()
    return [p for p in problems if not (p in seen or seen.add(p))]


def check_document(sections: Sequence[Section], facts: Mapping[str, Fact], extra_names: Iterable[str] = ()) -> CheckResult:
    """`facts` : tous les faits de l'utilisateur (le statut distingue validé et à valider).

    `extra_names` : mots que le texte peut citer sans fait (intitulé et entreprise de l'offre visée, pour
    une lettre) ; ils n'excusent que les noms propres, jamais un nombre, une date, une technologie ou un diplôme.
    """
    issues = []
    lexicon = TECHNOLOGIES | {fold(t) for f in facts.values() for t in f.technologies}
    extra_names = list(extra_names)
    for s, section in enumerate(sections):
        for b, bullet in enumerate(section.bullets):
            ids = [str(i) for i in bullet.fact_ids]

            def add(code: str, message: str, s: int = s, b: int = b) -> None:
                issues.append(Issue(s, b, code, message))

            if not ids:
                add("no_fact_ids", "Cette ligne ne cite aucun fait : elle n'est pas justifiée.")
                continue
            cited = []
            for fact_id in dict.fromkeys(ids):
                fact = facts.get(fact_id)
                if fact is None:
                    add("unknown_fact", "Cette ligne cite un fait qui n'existe pas dans votre profil.")
                elif fact.status != "validated":
                    add("unvalidated_fact", f"Le fait « {fact.text[:60]} » n'est pas encore validé.")
                else:
                    cited.append(fact)
            if not cited:
                continue
            cited_ids = {f.id for f in cited}
            other = " ".join(f"{f.text} {' '.join(f.technologies)}" for f in facts.values() if f.id not in cited_ids)
            for code, message in _check_line(bullet.texte, _Evidence(cited, extra_names), lexicon,
                                             set(re.findall(r"[a-z0-9]+", fold(other)))):
                add(code, message)
    return CheckResult(tuple(issues))
