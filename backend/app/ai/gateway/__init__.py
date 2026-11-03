"""Passerelle LLM (`ai/gateway`) : tout appel à un modèle de langage passe par `LLMGateway`."""

from app.ai.gateway.claude import ClaudeProvider, ModelSpec, ProviderError
from app.ai.gateway.factory import build_gateway, shared_gateway
from app.ai.gateway.gateway import (
    BudgetExceeded,
    GatewayError,
    GatewayResult,
    LLMGateway,
    ProviderNotAllowed,
)
from app.ai.gateway.provider import (
    DataKind,
    FakeProvider,
    LLMProvider,
    ProviderRequest,
    ProviderResponse,
)
from app.ai.gateway.pseudonymize import Pseudonymizer

__all__ = [
    "BudgetExceeded", "ClaudeProvider", "DataKind", "FakeProvider", "GatewayError", "GatewayResult",
    "LLMGateway", "LLMProvider", "ModelSpec", "ProviderError", "ProviderNotAllowed", "ProviderRequest",
    "ProviderResponse", "Pseudonymizer", "build_gateway", "shared_gateway",
]
