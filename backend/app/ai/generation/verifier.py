"""Second regard sur un texte généré : un modèle relit chaque ligne face aux faits qu'elle cite.

Il passe par la passerelle (pseudonymisation, plafond, cache) et vient **en plus** du contrôle
déterministe, qui reste prioritaire : le vérificateur ne peut qu'ajouter des rejets, jamais en lever.
Sa réponse est une donnée non fiable : schéma strict, toutes les lignes doivent être jugées, sinon
le texte n'est pas considéré comme vérifié (on refuse plutôt que d'accepter par défaut).
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

from app.ai.gateway import DataKind, GatewayError, LLMGateway
from app.ai.generation.factcheck import CheckResult, Issue, check_document
from app.ai.generation.schema import Fact, Section

PROMPT_VERSION = "verifier-v1"
INSTRUCTIONS = f"""Tu es un vérificateur factuel. Pour chaque ligne d'un CV ou d'une lettre, tu reçois les faits
qu'elle cite. Une ligne est « supported » seulement si TOUT ce qu'elle affirme (chiffres, dates, employeurs,
diplômes, outils, responsabilités, résultats, niveau de maîtrise) découle des faits cités. Une exagération,
un ajout ou une déduction non écrite rend la ligne non supportée. Réponds par UN SEUL objet JSON, sans texte
autour : {{"results": [{{"ref": "<ref de la ligne>", "supported": true ou false, "reason": "motif court"}}]}},
avec exactement une entrée par ligne reçue. Version du format : {PROMPT_VERSION}."""
Reason = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    ref: str
    supported: bool
    reason: Reason = ""


class Verdicts(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    results: list[Verdict]


def verify_with_llm(gateway: LLMGateway, user_id: str, sections: Sequence[Section], facts: Mapping[str, Fact],
                    known_names: Iterable[str]) -> list[Issue]:
    """Rejets ajoutés par le modèle. Réponse invalide, incomplète ou passerelle en échec : un rejet
    `verifier_unavailable` (le texte n'est pas vérifié, donc pas accepté)."""
    lines = {f"{s}.{b}": (s, b, bullet) for s, section in enumerate(sections) for b, bullet in enumerate(section.bullets)}
    if not lines:
        return []
    payload = [{"ref": ref, "ligne": bullet.texte,
                "faits": [{"kind": facts[str(i)].kind, "texte": facts[str(i)].text,
                           "debut": str(facts[str(i)].start_date or ""), "fin": str(facts[str(i)].end_date or ""),
                           "technologies": list(facts[str(i)].technologies)}
                          for i in bullet.fact_ids if str(i) in facts and facts[str(i)].status == "validated"]}
               for ref, (_, _, bullet) in lines.items()]
    unavailable = [Issue(0, 0, "verifier_unavailable", "Le vérificateur n'a pas pu relire le texte : il n'est pas vérifié.")]
    try:
        reply = gateway.call(user_id, purpose="verify_document", kind=DataKind.PROFILE, instructions=INSTRUCTIONS,
                             data=json.dumps(payload, ensure_ascii=False), known_names=known_names,
                             max_output_tokens=min(4000, 80 + 70 * len(lines)),
                             use_cache=False)  # une réponse invalide ne doit pas rester en cache
        body = reply.text.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", body, re.DOTALL)
        verdicts = Verdicts.model_validate_json(fenced.group(1) if fenced else body).results
    except (GatewayError, ValidationError):
        return unavailable
    if sorted(v.ref for v in verdicts) != sorted(lines):
        return unavailable
    return [Issue(lines[v.ref][0], lines[v.ref][1], "verifier_rejected",
                  f"Le vérificateur juge cette ligne non supportée par les faits : {v.reason or 'sans motif'}")
            for v in verdicts if not v.supported]


def full_check(gateway: LLMGateway, user_id: str, sections: Sequence[Section], facts: Mapping[str, Fact],
               known_names: Iterable[str], extra_names: Iterable[str] = ()) -> CheckResult:
    """Contrôle déterministe d'abord ; le vérificateur ne tourne que si ce contrôle passe (inutile de payer
    un appel pour un texte déjà bloqué)."""
    result = check_document(sections, facts, extra_names)
    if not result.ok:
        return result
    return CheckResult(tuple(verify_with_llm(gateway, user_id, sections, facts, known_names)))
