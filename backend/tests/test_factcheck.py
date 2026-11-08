import datetime as dt
import json
import uuid

import pytest
from test_ai_gateway import users  # noqa: F401  (fixture partagée)

from app.ai.gateway import FakeProvider, LLMGateway
from app.ai.generation.factcheck import check_document
from app.ai.generation.schema import Bullet, Fact, Section
from app.ai.generation.verifier import full_check, verify_with_llm

# Faits entièrement fictifs.
STAGE = Fact(str(uuid.uuid4()), "experience", "Stage de data analyst de 6 mois chez Acme : tableaux de bord de ventes",
             dt.date(2026, 1, 5), dt.date(2026, 6, 30), ("Python", "SQL"), "saisie manuelle", "validated")
MASTER = Fact(str(uuid.uuid4()), "education", "Master Data Science à l'Université Fictive", dt.date(2024, 9, 1),
              dt.date(2026, 6, 30), (), None, "validated")
SPARK = Fact(str(uuid.uuid4()), "skill", "Traitement de gros volumes avec Spark", None, None, ("Spark",), None, "validated")
PROPOSED = Fact(str(uuid.uuid4()), "skill", "Docker", None, None, ("Docker",), None, "proposed")
FACTS = {f.id: f for f in (STAGE, MASTER, SPARK, PROPOSED)}


def doc(*lines, ids=(STAGE,)):
    return [Section(section="Expérience", bullets=[Bullet(texte=t, fact_ids=[f.id for f in ids]) for t in lines])]


def codes(sections, **kwargs):
    return [i.code for i in check_document(sections, FACTS, **kwargs).issues]


@pytest.mark.parametrize("line", [
    "Réalisé un stage de data analyst de 6 mois chez Acme",
    "Conçu des tableaux de bord de ventes avec Python et SQL",
    "Stage chez Acme de janvier 2026 à juin 2026",
    "Stage du 05/01/2026 au 30/06/2026",
    "Analysé les ventes (Python, SQL)",
])
def test_lines_supported_by_their_facts_pass(line):
    assert codes(doc(line)) == []


@pytest.mark.parametrize(("line", "code"), [
    ("Maîtrise de Kubernetes et Python", "technology_not_in_facts"),  # compétence inventée
    ("Développé des modèles avec Kubeflow", "name_not_in_facts"),
    ("Stage de 8 mois chez Acme", "number_not_in_facts"),  # durée modifiée
    ("Stage de huit mois chez Acme", "number_not_in_facts"),
    ("Stage chez Acme de janvier 2025 à juin 2025", "number_not_in_facts"),  # année modifiée
    ("Stage chez Acme de mars 2026 à juin 2026", "date_not_in_facts"),  # mois modifié
    ("Stage de data analyst chez Globex", "name_not_in_facts"),  # employeur inventé
    ("Stage chez globex", "name_not_in_facts"),
    ("Titulaire d'un Doctorat en statistiques", "degree_not_in_facts"),
    ("Titulaire d'un bac +5", "degree_not_in_facts"),
    ("Augmenté les ventes de 35 %", "number_not_in_facts"),
    ("Utilisé les KPI de pilotage", "name_not_in_facts"),  # sigle absent
    ("Globex a embauché l'équipe", "name_not_in_facts"),  # nom propre en début de ligne
    ("Utilisation de Docker en production", "technology_not_in_facts"),  # le fait Docker n'est pas cité
])
def test_unjustified_content_is_rejected_with_a_reason(line, code):
    issues = check_document(doc(line), FACTS).issues
    assert code in [i.code for i in issues], line
    assert all(i.message for i in issues)


def test_every_line_needs_a_validated_fact():
    sections = [Section(section="Expérience", bullets=[
        Bullet(texte="Stage chez Acme", fact_ids=[]),
        Bullet(texte="Docker en production", fact_ids=[uuid.UUID(PROPOSED.id)]),
        Bullet(texte="Stage chez Acme", fact_ids=[uuid.uuid4()]),
        Bullet(texte="Stage chez Acme", fact_ids=[uuid.UUID(STAGE.id), uuid.UUID(PROPOSED.id)]),
    ])]
    result = check_document(sections, FACTS)
    assert [(i.bullet, i.code) for i in result.issues] == [
        (0, "no_fact_ids"), (1, "unvalidated_fact"), (2, "unknown_fact"), (3, "unvalidated_fact")]


def test_several_facts_support_a_line_together_but_not_a_fact_that_is_not_cited():
    line = "Master Data Science ; stage chez Acme ; Spark"
    assert codes(doc(line, ids=(STAGE, MASTER, SPARK))) == []
    assert "technology_not_in_facts" in codes(doc(line, ids=(STAGE, MASTER)))


def test_offer_words_excuse_names_only():
    letter = doc("Je candidate au poste d'analyste de Globex")
    assert "name_not_in_facts" in codes(letter)
    assert codes(letter, extra_names=["Globex"]) == []
    assert "number_not_in_facts" in codes(doc("Stage de 12 mois chez Acme"), extra_names=["12"])


def test_sentence_start_verb_is_tolerated_only_if_it_is_not_another_facts_name():
    assert codes(doc("Automatisé le reporting chez Acme")) == []
    other = Fact(str(uuid.uuid4()), "experience", "Stage chez Initech", None, None, (), None, "validated")
    result = check_document(doc("Initech a recruté chez Acme"), {**FACTS, other.id: other})
    assert "name_not_in_facts" in [i.code for i in result.issues]


@pytest.mark.parametrize(("line", "code", "kwargs"), [
    ("J'ai travaillé chez Google sur Python", "name_not_in_facts", {"extra_names": ["Google"]}),  # offre ≠ employeur
    ("Airbus : analyse de ventes avec Python", "name_not_in_facts", {}),
    ("Bouygues a employé Python", "name_not_in_facts", {}),
    ("Déploiement kubern\u0435tes", "invalid_characters", {}),  # e cyrillique
    ("Gestion de 1\u200b5 projets", "invalid_characters", {}),  # espace de largeur nulle
    ("Pilotage de seize projets", "number_not_in_facts", {}),
    ("Plus de quatre-vingts clients", "number_not_in_facts", {}),
    ("Des millions de lignes traitées", "number_not_in_facts", {}),
    ("Diplômé ingénieur en informatique", "degree_not_in_facts", {}),
    ("Titulaire d'une maîtrise", "degree_not_in_facts", {}),
    ("Stage du 06/01/2026 au 30/06/2026", "date_not_in_facts", {}),  # jour modifié
    ("Stage du 6 janvier 2026", "date_not_in_facts", {}),
])
def test_evasions_found_by_the_cold_review_are_rejected(line, code, kwargs):
    assert code in codes(doc(line), **kwargs), line


def test_days_and_months_of_dates_are_not_quantities():
    dated = Fact(str(uuid.uuid4()), "experience", "Stage chez Acme", dt.date(2021, 3, 15), None, ("Python",), None,
                 "validated")
    sections = [Section(section="Expérience", bullets=[Bullet(texte="15 ans de Python chez Acme",
                                                              fact_ids=[uuid.UUID(dated.id)])])]
    assert "number_not_in_facts" in [i.code for i in check_document(sections, {dated.id: dated}).issues]


def test_section_title_cannot_carry_an_invention():
    sections = [Section(section="Expert Kubernetes 2015", bullets=[Bullet(texte="Stage chez Acme",
                                                                          fact_ids=[uuid.UUID(STAGE.id)])])]
    assert {"technology_not_in_facts", "number_not_in_facts"} <= {i.code for i in check_document(sections, FACTS).issues}


def verdicts(*, rejected=(), skip=()):
    def reply(request):
        refs = [r["ref"] for r in json.loads(request.data.split("\n")[1])]
        return json.dumps({"results": [{"ref": r, "supported": r not in rejected, "reason": "ajout non écrit"}
                                       for r in refs if r not in skip]})
    return reply


def test_verifier_adds_rejections_through_the_gateway(users):  # noqa: F811
    alice, _ = users
    provider = FakeProvider(reply=verdicts(rejected={"0.1"}))
    sections = doc("Stage chez Acme", "Analysé les ventes avec Python")
    issues = verify_with_llm(LLMGateway(provider, daily_cap_eur=1.0), alice, sections, FACTS, [])
    assert [(i.bullet, i.code) for i in issues] == [(1, "verifier_rejected")]
    assert "Stage de data analyst" in provider.received[0].data  # les faits cités accompagnent la ligne


def test_incomplete_or_invalid_verifier_answer_is_not_a_pass(users):  # noqa: F811
    alice, _ = users
    sections = doc("Stage chez Acme", "Analysé les ventes avec Python")
    for reply in (verdicts(skip={"0.1"}), lambda request: "pas du json", lambda request: '{"results": []}'):
        issues = verify_with_llm(LLMGateway(FakeProvider(reply=reply), daily_cap_eur=1.0), alice, sections, FACTS, [])
        assert [i.code for i in issues] == ["verifier_unavailable"]


def test_deterministic_rejection_cannot_be_lifted_by_the_verifier(users):  # noqa: F811
    alice, _ = users
    provider = FakeProvider(reply=verdicts())  # le vérificateur approuve tout
    result = full_check(LLMGateway(provider, daily_cap_eur=1.0), alice, doc("Maîtrise de Kubernetes"), FACTS, [])
    assert not result.ok and provider.received == []
    assert full_check(LLMGateway(provider, daily_cap_eur=1.0), alice, doc("Stage chez Acme"), FACTS, []).ok


@pytest.mark.parametrize("line", [
    "Étudiant en Master Data Science",
    "Étudiante en Master Data Science",
    "Projets de développement en Python",
    "Outils : Python, SQL",
    "Développeur Python en stage chez Acme",
    "Stagiaire data analyst chez Acme",
    "Compétences : Python et SQL",
])
def test_common_nouns_at_line_start_are_not_mistaken_for_names(line):
    assert "name_not_in_facts" not in codes(doc(line, ids=(STAGE, MASTER, SPARK))), line


@pytest.mark.parametrize("line", [
    "Capgemini : mission de data analyst",
    "Google a recruté un data analyst",
    "Étudiant chez Google",  # le nom propre reste rejeté même derrière un mot courant
    "Webex pour les réunions",  # ressemble à « web » sans en être un
    "Projets chez Globex",
])
def test_invented_names_at_line_start_are_still_rejected(line):
    assert "name_not_in_facts" in codes(doc(line, ids=(STAGE, MASTER, SPARK))), line
