"""Fournisseur Claude (API Anthropic « Messages ») : appel HTTP direct, sans SDK.

Ne se construit que par `factory.py` ; ne s'appelle que depuis `LLMGateway`. La clé vient de
`ANTHROPIC_API_KEY` et n'est ni affichée (`repr`), ni journalisée, ni recopiée dans une erreur : toute
panne devient une `ProviderError` au message fixe. Aucune nouvelle tentative sur une erreur
d'authentification (une clé fausse ne se répare pas en insistant).
"""

import dataclasses
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import ClassVar

import httpx

from app.ai.gateway.provider import DataKind, LLMProvider, ProviderRequest, ProviderResponse

log = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
TIMEOUT_SECONDS = 90.0  # une génération de CV (3000 jetons) peut durer une minute
MAX_RETRIES = 2  # deux nouvelles tentatives au plus, donc trois appels
RETRY_BASE_SECONDS = 2.0
RETRY_MAX_SECONDS = 20.0  # plafond du délai, même si l'API demande plus (en-tête retry-after)
# Usages (`purpose` de la passerelle) confiés au modèle de qualité ; tous les autres vont au modèle rapide.
QUALITY_PURPOSES = frozenset({"generate_document"})


class ProviderError(Exception):
    """Échec de l'appel ; le message est fixe, jamais un texte venu de la requête ou de la réponse."""


@dataclass(frozen=True)
class ModelSpec:
    """Un modèle et son tarif en euros par million de jetons. Valeurs par défaut : voir `factory.py`."""

    name: str
    eur_per_mtok_input: float
    eur_per_mtok_output: float


@dataclass(frozen=True)
class ClaudeProvider(LLMProvider):
    api_key: str = field(repr=False)
    fast: ModelSpec
    quality: ModelSpec
    transport: httpx.BaseTransport | None = field(default=None, repr=False)  # tests : transport simulé
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)
    spec: ModelSpec | None = None  # modèle de la tâche en cours (voir `for_purpose`)

    name: ClassVar[str] = "anthropic"
    # Données pseudonymisées du profil acceptées (la passerelle pseudonymise toujours avant l'envoi) ;
    # les conditions commerciales de l'API n'entraînent pas les modèles sur nos données (à revérifier).
    accepted_data: ClassVar[frozenset[DataKind]] = frozenset(DataKind)
    reuses_data: ClassVar[bool] = False

    def __post_init__(self) -> None:
        if not self.api_key:
            raise ValueError("clé API absente")

    @property
    def _spec(self) -> ModelSpec:
        return self.spec or self.fast

    @property
    def model(self) -> str:  # type: ignore[override]
        return self._spec.name

    @property
    def eur_per_mtok_input(self) -> float:  # type: ignore[override]
        return self._spec.eur_per_mtok_input

    @property
    def eur_per_mtok_output(self) -> float:  # type: ignore[override]
        return self._spec.eur_per_mtok_output

    def for_purpose(self, purpose: str) -> "ClaudeProvider":
        return dataclasses.replace(self, spec=self.quality if purpose in QUALITY_PURPOSES else self.fast)

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        body = {"model": self.model, "max_tokens": request.max_output_tokens, "system": request.instructions,
                "messages": [{"role": "user", "content": request.data}]}
        headers = {"x-api-key": self.api_key, "anthropic-version": API_VERSION}
        with httpx.Client(transport=self.transport, timeout=TIMEOUT_SECONDS) as client:
            for attempt in range(MAX_RETRIES + 1):
                delay = min(RETRY_BASE_SECONDS * 2 ** attempt, RETRY_MAX_SECONDS)
                try:
                    reply = client.post(API_URL, json=body, headers=headers)
                except httpx.TransportError:
                    error = "le service Claude ne répond pas"
                else:
                    if reply.status_code == 200:
                        return self._parse(reply)
                    if reply.status_code in (401, 403):
                        raise ProviderError("clé API refusée par Anthropic (401/403)") from None
                    if reply.status_code not in (429, 500, 502, 503, 504, 529):
                        raise ProviderError(f"requête refusée par Anthropic (HTTP {reply.status_code})") from None
                    error = f"Anthropic indisponible ou limite atteinte (HTTP {reply.status_code})"
                    delay = _retry_after(reply, delay)
                if attempt == MAX_RETRIES:
                    raise ProviderError(error) from None
                log.warning("appel Claude à refaire (essai %d) : %s", attempt + 1, error)
                self.sleep(delay)
        raise ProviderError("appel Claude impossible")  # inatteignable

    @staticmethod
    def _parse(reply: httpx.Response) -> ProviderResponse:
        try:
            data = reply.json()
            text = "".join(block["text"] for block in data["content"] if block.get("type") == "text")
            usage = data["usage"]
            return ProviderResponse(text, int(usage["input_tokens"]), int(usage["output_tokens"]))
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ProviderError("réponse d'Anthropic illisible") from None


def _retry_after(reply: httpx.Response, default: float) -> float:
    try:
        return min(max(float(reply.headers.get("retry-after", "")), 0.0), RETRY_MAX_SECONDS)
    except ValueError:
        return default
