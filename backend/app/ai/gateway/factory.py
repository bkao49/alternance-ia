"""Construit la passerelle LLM à partir de l'environnement (API et worker partagent ce chemin).

`LLM_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` : fournisseur Claude. Sinon `None` : les fonctions d'IA
répondent « fournisseur non configuré » au lieu de planter. La clé n'est jamais dans un message.
"""

import functools
import logging
import os

from app.ai.gateway.claude import ClaudeProvider, ModelSpec
from app.ai.gateway.gateway import LLMGateway

log = logging.getLogger(__name__)

# Tarifs en euros par million de jetons. À REVÉRIFIER sur anthropic.com/pricing (valeurs prudentes,
# dollars comptés comme des euros) ; modifiables par ANTHROPIC_EUR_PER_MTOK_{FAST,QUALITY}_{IN,OUT}.
DEFAULT_FAST = ModelSpec("claude-haiku-5-5", 1.0, 5.0)
DEFAULT_QUALITY = ModelSpec("claude-sonnet-5-5", 3.0, 15.0)


def _price(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    try:
        value = float(raw) if raw else default
    except ValueError:
        raise RuntimeError(f"{name} doit être un nombre") from None
    if not 0 <= value <= 1000:
        raise RuntimeError(f"{name} doit être compris entre 0 et 1000")
    return value


def _spec(tier: str, default: ModelSpec) -> ModelSpec:
    return ModelSpec(os.environ.get(f"ANTHROPIC_MODEL_{tier}") or default.name,
                     _price(f"ANTHROPIC_EUR_PER_MTOK_{tier}_IN", default.eur_per_mtok_input),
                     _price(f"ANTHROPIC_EUR_PER_MTOK_{tier}_OUT", default.eur_per_mtok_output))


def provider_name() -> str:
    return os.environ.get("LLM_PROVIDER", "").strip().lower()


def build_gateway() -> LLMGateway | None:
    """None si aucun fournisseur n'est choisi ou si sa clé manque ; erreur claire si le choix est inconnu."""
    name = provider_name()
    if not name:
        return None
    if name != "anthropic":
        raise RuntimeError("LLM_PROVIDER inconnu (valeur acceptée : anthropic)")
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        return None
    return LLMGateway(ClaudeProvider(api_key=key, fast=_spec("FAST", DEFAULT_FAST),
                                     quality=_spec("QUALITY", DEFAULT_QUALITY)))


@functools.cache
def shared_gateway() -> LLMGateway | None:
    """Une seule passerelle par processus. Les tests vident le cache avec `shared_gateway.cache_clear()`."""
    try:
        return build_gateway()
    except RuntimeError:  # réglage invalide : l'IA reste désactivée au lieu de faire planter le worker ou l'API
        log.error("réglage de l'IA invalide : IA désactivée (lancez « docker compose run --rm doctor »)")
        return None
