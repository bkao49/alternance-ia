"""Interface des fournisseurs LLM et fournisseur factice pour les tests.

Aucun vrai fournisseur n'est branché ici : chaque adaptateur réel (Claude, etc.) arrivera dans sa
propre PR, avec sa clé lue depuis l'environnement et jamais versionnée.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar


class DataKind(StrEnum):
    """Nature des données envoyées : décide quels fournisseurs ont le droit de les recevoir."""

    JOB_POSTING = "job_posting"  # texte d'annonce publique, sans donnée de l'utilisateur
    PROFILE = "profile"  # CV, faits du profil, critères : données personnelles


PERSONAL_KINDS = frozenset({DataKind.PROFILE})


@dataclass(frozen=True)
class ProviderRequest:
    instructions: str  # consignes écrites par notre code : seule partie traitée comme instruction
    data: str  # données délimitées (annonce, profil pseudonymisé) : jamais des instructions
    max_output_tokens: int


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    input_tokens: int
    output_tokens: int


class LLMProvider(ABC):
    name: ClassVar[str]
    model: ClassVar[str]
    # Prix en euros par million de jetons, pour le plafond de coût.
    eur_per_mtok_input: ClassVar[float]
    eur_per_mtok_output: ClassVar[float]
    # Types de données acceptés (liste blanche) et réutilisation des données par le fournisseur
    # (entraînement, revue humaine) : un fournisseur qui réutilise ne reçoit jamais de donnée personnelle.
    accepted_data: ClassVar[frozenset[DataKind]]
    reuses_data: ClassVar[bool]

    @abstractmethod
    def complete(self, request: ProviderRequest) -> ProviderResponse:
        """Seule méthode qui touche au réseau."""

    def cost_eur(self, input_tokens: int, output_tokens: int) -> float:
        return (input_tokens * self.eur_per_mtok_input + output_tokens * self.eur_per_mtok_output) / 1_000_000

    def allows(self, kind: DataKind) -> bool:
        if kind in PERSONAL_KINDS and self.reuses_data:
            return False
        return kind in self.accepted_data


def estimate_tokens(text: str) -> int:
    """Estimation prudente (environ 4 caractères par jeton, arrondi au-dessus)."""
    return len(text) // 4 + 1


@dataclass
class FakeProvider(LLMProvider):
    """Fournisseur factice : aucune requête réseau. Il garde les requêtes reçues pour les tests."""

    reply: Callable[[ProviderRequest], str] = lambda request: "réponse factice"
    received: list[ProviderRequest] = field(default_factory=list)

    name: ClassVar[str] = "fake"
    model: ClassVar[str] = "fake-1"
    eur_per_mtok_input: ClassVar[float] = 1.0
    eur_per_mtok_output: ClassVar[float] = 2.0
    accepted_data: ClassVar[frozenset[DataKind]] = frozenset(DataKind)
    reuses_data: ClassVar[bool] = False

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        self.received.append(request)
        text = self.reply(request)
        return ProviderResponse(text, estimate_tokens(request.instructions + request.data), estimate_tokens(text))
