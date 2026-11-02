"""Commande `python -m app.doctor` : base réelle, sources simulées, aucune clé ni réseau."""
import httpx
import psycopg

from app import doctor
from app.ai.gateway.claude import check_api_key

SECRET = "valeur-secrete-qui-ne-doit-jamais-sortir-0000"
EMPTY = {"SECRET_KEY": "x" * 32}


def text(lines):
    return "\n".join(f"{line.level} {line.message}" for line in lines)


def test_database_and_migrations_up_to_date(migrated_db):
    lines = doctor.check_database({"DATABASE_URL": migrated_db})
    assert [line.level for line in lines] == [doctor.OK, doctor.OK]
    assert "à jour" in lines[1].message


def test_outdated_migrations_are_reported_with_the_fix(migrated_db):
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        conn.execute("UPDATE alembic_version SET version_num = '0001'")
    lines = doctor.check_database({"DATABASE_URL": migrated_db})
    assert lines[-1].level == doctor.ERROR and "docker compose run --rm migrate" in lines[-1].message


def test_unreachable_database_never_prints_the_url():
    url = f"postgresql://moi:{SECRET}@127.0.0.1:1/app"
    out = text(doctor.check_database({"DATABASE_URL": url}))
    assert doctor.ERROR in out and SECRET not in out and "127.0.0.1" not in out
    assert doctor.ERROR in text(doctor.check_database({}))


def test_keys_are_reported_yes_or_no_never_their_value():
    env = {**EMPTY, "ANTHROPIC_API_KEY": SECRET, "ADZUNA_APP_ID": SECRET, "LLM_PROVIDER": "anthropic"}
    out = text(doctor.check_keys(env))
    assert SECRET not in out
    assert "Clé ANTHROPIC_API_KEY : renseignée" in out
    assert "ADZUNA_APP_ID et ADZUNA_APP_KEY : absente" in out  # une moitié ne suffit pas
    assert "LBA_API_TOKEN (La Bonne Alternance) : absente" in out and "francetravail.io" in out


def test_missing_secret_key_and_unknown_provider_are_blocking():
    lines = doctor.check_keys({"SECRET_KEY": "court", "LLM_PROVIDER": "gemini"})
    assert sum(line.level == doctor.ERROR for line in lines) == 2
    assert any("LLM_PROVIDER" in line.message and line.level == doctor.TODO
               for line in doctor.check_keys(EMPTY))


def test_sources_each_get_a_test_call_and_failures_stay_readable():
    def boom():
        raise RuntimeError(SECRET)

    lines = doctor.check_sources({"Adzuna": lambda: None, "La Bonne Alternance": lambda: "clé refusée (401)",
                                  "Claude (Anthropic)": boom})
    out = text(lines)
    assert [line.level for line in lines] == [doctor.OK, doctor.ERROR, doctor.ERROR]
    assert "clé refusée (401)" in out and SECRET not in out and "RuntimeError" in out
    assert doctor.TODO in text(doctor.check_sources({}))


def test_only_configured_sources_are_probed():
    assert doctor.default_probes(EMPTY) == {}
    assert set(doctor.default_probes({"ADZUNA_APP_ID": "a", "ADZUNA_APP_KEY": "b", "ANTHROPIC_API_KEY": "c"})) \
        == {"Adzuna", "Claude (Anthropic)"}


def test_anthropic_key_check_uses_the_free_models_endpoint():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(401 if request.headers["x-api-key"] == "mauvaise" else 200, json={})

    transport = httpx.MockTransport(handler)
    assert check_api_key("bonne", transport) is None
    assert "refusée" in check_api_key("mauvaise", transport)
    assert seen[0].method == "GET" and seen[0].url.path == "/v1/models"  # aucune génération, aucun jeton payé


def test_run_assembles_all_sections(migrated_db):
    lines = doctor.run({**EMPTY, "DATABASE_URL": migrated_db}, probes={})
    assert len(lines) >= 8 and lines[0].level == doctor.OK
