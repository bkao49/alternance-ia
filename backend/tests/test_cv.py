import io
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import psycopg
import pytest
from cvfiles import make_docx, make_pdf
from sqlalchemy import text
from test_applications import (  # noqa: F401  (fixtures et helpers partagés)
    alice,
    application,
    assert_conforms,
    bob,
    contract,
)

from app.cv import files, routes, sandbox
from app.db import user_scope

PDF = "application/pdf"


def upload(api, data, name="cv.pdf", headers=None):
    return api.client.post("/profile/cv", files={"file": (name, data, PDF)},
                           headers={"X-CSRF-Token": api.client.cookies["csrf_token"], **(headers or {})})


def wait_done(api):
    for _ in range(100):
        body = api.get("/profile/cv").json()
        if body["status"] != "processing":
            return body
        time.sleep(0.1)
    raise AssertionError("extraction trop longue")


def test_pdf_and_docx_are_accepted_and_extracted(alice, contract):  # noqa: F811
    for data, name, kind in ((make_pdf(), "mon cv.pdf", "pdf"), (make_docx(), "cv.docx", "docx")):
        response = upload(alice, data, name)
        assert response.status_code == 202, response.text
        assert_conforms(contract, "ProfileCv", response.json())
        done = wait_done(alice)
        assert (done["status"], done["file_type"], done["original_name"]) == ("done", kind, name)


@pytest.mark.parametrize("data", [
    b"MZ\x90\x00 fichier executable", b"just text", b"<html>", b"PK\x03\x04 faux zip",
    make_pdf(extra=b"/JavaScript (app.alert(1))"), make_pdf(extra=b"/Launch"), make_pdf(extra=b"/Encrypt 9 0 R"), make_pdf(extra=b"/#4AavaScript (x)"),
])
def test_wrong_or_fake_types_are_refused_whatever_the_name(alice, data):  # noqa: F811
    assert upload(alice, data, "cv.pdf").status_code == 415
    assert alice.get("/profile/cv").status_code == 404


def test_docx_traps_are_refused(alice):  # noqa: F811
    traps = [
        make_docx(extra={"word/vbaProject.bin": b"x"}),
        make_docx(extra={"../evil.txt": b"x"}),
        make_docx(extra={"big.bin": b"0" * 10_000_000}),  # taux de compression énorme : zip bombe
        make_docx(extra={f"f{i}.txt": b"x" for i in range(300)}),
    ]
    assert [upload(alice, trap, "cv.docx").status_code for trap in traps] == [415] * 4
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("note.txt", "x")
    assert upload(alice, buffer.getvalue(), "cv.docx").status_code == 415


def test_size_limit(alice, monkeypatch):  # noqa: F811
    assert upload(alice, make_pdf() + b" " * (files.MAX_BYTES + 1)).status_code == 413
    assert upload(alice, b"").status_code in (415, 422)
    assert alice.get("/profile/cv").status_code == 404


def test_form_must_hold_one_file_field(alice):  # noqa: F811
    headers = {"X-CSRF-Token": alice.client.cookies["csrf_token"]}
    two = alice.client.post("/profile/cv", files={"file": ("a.pdf", make_pdf()), "other": ("b.pdf", make_pdf())},
                            headers=headers)
    assert two.status_code == 422
    assert alice.client.post("/profile/cv", json={"file": "x"}, headers=headers).status_code == 415
    assert alice.client.post("/profile/cv", files={"file": (None, "texte")}, headers=headers).status_code == 422


def test_name_is_only_for_display(alice):  # noqa: F811
    assert files.clean_name("../../etc/passwd\x00.pdf") == "passwd.pdf"
    assert files.clean_name("C:\\Users\\x\\cv\n.pdf") == "cv.pdf"
    assert files.clean_name("") == "cv" and len(files.clean_name("a" * 500)) == 120
    upload(alice, make_pdf(), "../../etc/passwd.pdf")
    assert alice.get("/profile/cv").json()["original_name"] == "passwd.pdf"


def test_upload_requires_session_and_csrf(alice, application):  # noqa: F811
    from fastapi.testclient import TestClient

    anonymous = TestClient(application, base_url="https://testserver")
    assert anonymous.post("/profile/cv", files={"file": ("a.pdf", make_pdf())}).status_code == 401
    assert alice.client.post("/profile/cv", files={"file": ("a.pdf", make_pdf())}).status_code == 403
    assert anonymous.get("/profile/cv").status_code == 401


def test_upload_quota(alice):  # noqa: F811
    assert [upload(alice, make_pdf()).status_code for _ in range(6)] == [202] * 5 + [429]
    assert alice.client.delete("/profile/cv", headers={"X-CSRF-Token": alice.client.cookies["csrf_token"]})
    assert upload(alice, make_pdf()).status_code == 429  # supprimer puis redéposer ne remet pas le quota à zéro


def test_blank_and_broken_files_fail_cleanly(alice):  # noqa: F811
    upload(alice, make_pdf([" "]))
    assert wait_done(alice)["error_code"] == "no_text"
    upload(alice, b"%PDF-1.4\ngarbage not a pdf")
    failed = wait_done(alice)
    assert failed["status"] == "failed" and failed["error_code"] in ("unreadable", "no_text")


def test_extraction_has_no_secret_and_a_deadline(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "secret-de-test-" + "x" * 30)
    probe = tmp_path / "probe.py"
    probe.write_text("import os, sys\nsys.stdout.write(repr(sorted(os.environ)))\n")
    monkeypatch.setattr(sandbox, "WORKER", probe)
    assert "SECRET_KEY" not in sandbox.subprocess.run(
        [sys.executable, "-I", str(probe)], capture_output=True, text=True,
        env={}, check=False).stdout
    slow = tmp_path / "slow.py"
    slow.write_text("import time\ntime.sleep(30)\n")
    monkeypatch.setattr(sandbox, "WORKER", slow)
    monkeypatch.setattr(sandbox, "TIMEOUT_SECONDS", 1)
    with pytest.raises(sandbox.ExtractionFailed) as error:
        sandbox.extract_text(b"%PDF-", "pdf")
    assert error.value.code == "timeout"


def test_worker_cannot_use_the_network():
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import extract_worker as w; w._no_network(); "
            "import socket\ntry:\n socket.create_connection(('example.com', 80))\nexcept OSError: print('bloque')")
    out = subprocess.run([sys.executable, "-I", "-c", code, str(Path(sandbox.WORKER).parent)],
                         capture_output=True, text=True, check=False)
    assert out.stdout.strip() == "bloque"


def test_worker_runs_in_the_sandbox_and_reads_text():
    assert "Stage data analyst" in sandbox.extract_text(make_pdf(), "pdf")
    assert "Stage data analyst" in sandbox.extract_text(make_docx(), "docx")
    with pytest.raises(sandbox.ExtractionFailed):
        sandbox.extract_text(b"%PDF-1.4 nope", "pdf")


def download(api, link):
    return api.get(link["url"])


def test_signed_download(alice, bob, monkeypatch, contract):  # noqa: F811
    data = make_pdf()
    upload(alice, data, "../x.pdf")
    link = alice.client.post("/profile/cv/download-link", headers={"X-CSRF-Token": alice.client.cookies["csrf_token"]})
    assert link.status_code == 200
    assert_conforms(contract, "CvDownloadLink", link.json())
    fetched = alice.get(link.json()["url"])
    assert fetched.status_code == 200 and fetched.content == data
    assert fetched.headers["content-disposition"] == 'attachment; filename="cv.pdf"'
    assert fetched.headers["x-content-type-options"] == "nosniff" and fetched.headers["cache-control"] == "no-store"
    # Le lien d'Alice ne marche pas pour Bob, ni falsifié, ni expiré.
    assert bob.get(link.json()["url"]).status_code == 404
    assert alice.get(link.json()["url"][:-3] + "abc").status_code == 404
    assert alice.get("/profile/cv/file/n-importe-quoi").status_code == 404
    monkeypatch.setattr(routes, "LINK_SECONDS", -1)
    assert alice.get(link.json()["url"]).status_code == 404
    monkeypatch.setattr(routes, "LINK_SECONDS", 60)
    alice.client.delete("/profile/cv", headers={"X-CSRF-Token": alice.client.cookies["csrf_token"]})
    assert alice.get(link.json()["url"]).status_code == 404  # CV supprimé : le lien ne sert plus


def test_link_needs_a_cv_and_a_session(alice):  # noqa: F811
    headers = {"X-CSRF-Token": alice.client.cookies["csrf_token"]}
    assert alice.client.post("/profile/cv/download-link", headers=headers).status_code == 404
    assert alice.client.post("/profile/cv/download-link").status_code == 403


def test_users_are_isolated_down_to_the_database(alice, bob, migrated_db):  # noqa: F811
    upload(alice, make_pdf())
    assert bob.get("/profile/cv").status_code == 404
    assert bob.client.delete("/profile/cv", headers={"X-CSRF-Token": bob.client.cookies["csrf_token"]}
                             ).status_code == 404
    with user_scope(bob.user_id) as conn:
        assert conn.execute(text("SELECT count(*) FROM cv_documents")).scalar_one() == 0
    with psycopg.connect(migrated_db) as conn:
        conn.execute("SET ROLE app_rw")
        assert conn.execute("SELECT count(*) FROM cv_documents").fetchone()[0] == 0  # sans utilisateur : rien


def test_delete_removes_cv_and_its_facts_only(alice):  # noqa: F811
    upload(alice, make_pdf())
    manual = alice.post("/profile/facts", {"kind": "skill", "text": "Pandas", "start_date": None,
                                           "end_date": None, "technologies": [], "source": None}).json()["id"]
    with user_scope(alice.user_id) as conn:
        cv_id = conn.execute(text("SELECT id FROM cv_documents")).scalar_one()
        for status in ("proposed", "validated"):
            conn.execute(text("INSERT INTO profile_facts (user_id, kind, text, status, cv_document_id) "
                              "VALUES (:u, 'skill', 'Python', :s, :c)"),
                         {"u": alice.user_id, "s": status, "c": cv_id})
    assert alice.client.delete("/profile/cv", headers={"X-CSRF-Token": alice.client.cookies["csrf_token"]}
                               ).status_code == 204
    assert [f["id"] for f in alice.get("/profile/facts").json()] == [manual]


def test_new_upload_replaces_cv_and_proposed_facts_but_keeps_validated(alice):  # noqa: F811
    upload(alice, make_pdf())
    with user_scope(alice.user_id) as conn:
        cv_id = conn.execute(text("SELECT id FROM cv_documents")).scalar_one()
        for status, label in (("proposed", "A relire"), ("validated", "Valide")):
            conn.execute(text("INSERT INTO profile_facts (user_id, kind, text, status, cv_document_id) "
                              "VALUES (:u, 'skill', :t, :s, :c)"),
                         {"u": alice.user_id, "t": label, "s": status, "c": cv_id})
    upload(alice, make_docx(), "nouveau.docx")
    assert [f["text"] for f in alice.get("/profile/facts").json()] == ["Valide"]
    assert alice.get("/profile/cv").json()["original_name"] == "nouveau.docx"
