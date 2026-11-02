"""Fournisseur Claude : transport HTTP simulé, aucune requête réseau, fausse clé."""
import json
import logging
import secrets

import httpx
import pytest

from app import db
from app.ai.gateway import (
    ClaudeProvider,
    DataKind,
    GatewayError,
    LLMGateway,
    ModelSpec,
    ProviderError,
    ProviderRequest,
    build_gateway,
)
from app.create_user import create_user

KEY = "sk-ant-fausse-cle-pour-les-tests-0000"
FAST = ModelSpec("modele-rapide", 1.0, 5.0)
QUALITY = ModelSpec("modele-qualite", 3.0, 15.0)
REQUEST = ProviderRequest("Consigne.", "Donnée.", 100)
GOOD = {"content": [{"type": "text", "text": "bonjour"}], "usage": {"input_tokens": 12, "output_tokens": 3}}


def provider(handler, sleeps=None, **kwargs):
    return ClaudeProvider(api_key=KEY, fast=FAST, quality=QUALITY, transport=httpx.MockTransport(handler),
                          sleep=(sleeps if sleeps is not None else []).append, **kwargs)


def test_sends_a_messages_request_and_reads_the_reply():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=GOOD)

    response = provider(handler).complete(REQUEST)
    assert (response.text, response.input_tokens, response.output_tokens) == ("bonjour", 12, 3)
    request = seen[0]
    body = json.loads(request.content)
    assert request.url == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == KEY and request.headers["anthropic-version"]
    assert body == {"model": "modele-rapide", "max_tokens": 100, "system": "Consigne.",
                    "messages": [{"role": "user", "content": "Donnée."}]}


def test_model_and_price_depend_on_the_task():
    base = provider(lambda r: httpx.Response(200, json=GOOD))
    assert base.for_purpose("extract_offer").model == "modele-rapide"
    assert base.for_purpose("verify_document").model == "modele-rapide"
    quality = base.for_purpose("generate_document")
    assert quality.model == "modele-qualite"
    assert quality.cost_eur(1_000_000, 1_000_000) == pytest.approx(18.0)


def test_policy_accepts_pseudonymised_profile_but_never_reuses_data():
    p = provider(lambda r: httpx.Response(200, json=GOOD))
    assert p.allows(DataKind.PROFILE) and p.allows(DataKind.JOB_POSTING) and not p.reuses_data


@pytest.mark.parametrize("status", [429, 503, 529])
def test_retries_then_succeeds(status):
    replies = iter([httpx.Response(status, headers={"retry-after": "3"}), httpx.Response(200, json=GOOD)])
    sleeps = []
    assert provider(lambda r: next(replies), sleeps).complete(REQUEST).text == "bonjour"
    assert sleeps == [3.0]


def test_retries_a_network_error_but_gives_up_after_the_limit():
    calls = []

    def handler(request):
        calls.append(1)
        raise httpx.ConnectError("boom " + KEY)  # même un message piégé ne doit pas ressortir

    sleeps = []
    with pytest.raises(ProviderError) as error:
        provider(handler, sleeps).complete(REQUEST)
    assert len(calls) == 3 and len(sleeps) == 2
    assert KEY not in str(error.value) and error.value.__cause__ is None


@pytest.mark.parametrize("status", [401, 403])
def test_never_retries_an_authentication_error(status):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status, json={"error": {"message": "invalid x-api-key " + KEY}})

    with pytest.raises(ProviderError) as error:
        provider(handler).complete(REQUEST)
    assert len(calls) == 1 and KEY not in str(error.value)


def test_other_client_errors_are_not_retried_and_hide_the_body():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "Donnée. fuite"}})

    with pytest.raises(ProviderError) as error:
        provider(handler).complete(REQUEST)
    assert len(calls) == 1 and "fuite" not in str(error.value)


@pytest.mark.parametrize("payload", [{"foo": 1}, {"content": [], "usage": {}}, "pas du json"])
def test_unreadable_reply_is_an_error(payload):
    with pytest.raises(ProviderError):
        provider(lambda r: httpx.Response(200, json=payload)).complete(REQUEST)


def test_key_is_not_in_repr_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    p = provider(lambda r: httpx.Response(429))
    with pytest.raises(ProviderError):
        p.complete(REQUEST)
    assert KEY not in repr(p) and KEY not in caplog.text


def test_missing_key_is_refused():
    with pytest.raises(ValueError):
        ClaudeProvider(api_key="", fast=FAST, quality=QUALITY)


def test_factory_reads_the_environment(monkeypatch):
    for name in ("LLM_PROVIDER", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL_FAST", "ANTHROPIC_EUR_PER_MTOK_FAST_IN"):
        monkeypatch.delenv(name, raising=False)
    assert build_gateway() is None  # rien de choisi
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert build_gateway() is None  # clé absente
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY)
    monkeypatch.setenv("ANTHROPIC_MODEL_FAST", "autre-modele")
    monkeypatch.setenv("ANTHROPIC_EUR_PER_MTOK_FAST_IN", "2.5")
    chosen = build_gateway().provider.for_purpose("extract_offer")
    assert (chosen.model, chosen.eur_per_mtok_input) == ("autre-modele", 2.5)
    assert build_gateway().provider.for_purpose("generate_document").model == "claude-sonnet-5-5"
    monkeypatch.setenv("LLM_PROVIDER", "inconnu")
    with pytest.raises(RuntimeError):
        build_gateway()


@pytest.fixture
def user(migrated_db, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", secrets.token_hex(32))
    yield create_user("alice@example.test", "mot-de-passe-de-test-123")
    db._engine(migrated_db).dispose()
    db._engine.cache_clear()


def test_gateway_logs_the_task_model_and_hides_provider_errors(user, migrated_db):
    import psycopg
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["model"])
        return httpx.Response(200, json=GOOD)

    gateway = LLMGateway(provider(handler), daily_cap_eur=1.0)
    gateway.call(user, purpose="generate_document", kind=DataKind.JOB_POSTING, instructions="a", data="b")
    gateway.call(user, purpose="extract_offer", kind=DataKind.JOB_POSTING, instructions="a", data="b")
    assert seen == ["modele-qualite", "modele-rapide"]
    with psycopg.connect(migrated_db) as conn:
        rows = conn.execute("SELECT purpose, model FROM llm_calls ORDER BY created_at").fetchall()
    assert rows == [("generate_document", "modele-qualite"), ("extract_offer", "modele-rapide")]

    failing = LLMGateway(provider(lambda r: httpx.Response(401, text=KEY)), daily_cap_eur=1.0)
    with pytest.raises(GatewayError) as error:
        failing.call(user, purpose="extract_offer", kind=DataKind.JOB_POSTING, instructions="a", data="c")
    assert KEY not in str(error.value)
