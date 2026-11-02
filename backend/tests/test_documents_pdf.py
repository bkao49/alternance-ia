# ruff: noqa: F811  (les fixtures importées sont reprises en argument)
import io

import pytest
from pypdf import PdfReader
from test_applications import (  # noqa: F401  (fixtures et helpers partagés)
    alice,
    application,
    bob,
    contract,
    insert_offer,
)
from test_documents import GOOD, MASTER, SPARK, STAGE, generate, ready, use_model  # noqa: F401

from app.ai.generation.schema import Bullet, Section
from app.documents_pdf import latin, render_pdf

ID = "00000000-0000-0000-0000-000000000001"


def sections(*lines):
    return [Section(section="Expérience", bullets=[Bullet(texte=t, fact_ids=[ID]) for t in lines]),
            Section(section="Compétences", bullets=[Bullet(texte="Python, SQL & Spark <3", fact_ids=[ID])])]


def words(pdf: bytes) -> str:
    return " ".join(" ".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages).split())


LINES = ["Stage de data analyst de 6 mois chez Acme (janvier → juin 2026)", "Conçu des tableaux de bord « ventes » – œuvre d'été",
         "Ligne très longue " + "avec beaucoup de mots " * 20 + "fin."]


def test_text_is_real_selectable_and_faithful():
    pdf = render_pdf("cv", sections(*LINES))
    assert pdf.startswith(b"%PDF")
    text = words(pdf)
    for line in LINES[:2]:
        assert latin(line) in text, line  # texte extrait fidèle au texte source (accents, guillemets, œ, tiret)
    assert latin(LINES[2]).strip() in text  # une ligne longue passe à la ligne sans rien perdre
    assert "Expérience" in text and "Python, SQL & Spark <3" in text
    assert text.index("Expérience") < text.index("Compétences")  # une seule colonne : ordre de lecture = ordre du texte


def test_pdf_is_plain_one_column_without_images_links_or_personal_metadata():
    pdf = render_pdf("cv", sections(*LINES))
    reader = PdfReader(io.BytesIO(pdf))
    for page in reader.pages:
        assert "/Annots" not in page  # ni lien ni champ
        resources = page["/Resources"]
        assert "/XObject" not in resources  # aucune image
        fonts = {resources["/Font"][name]["/BaseFont"] for name in resources["/Font"]}
        assert fonts <= {"/Helvetica", "/Helvetica-Bold"}  # polices standard, rien d'incorporé
        assert all("/FontFile" not in str(resources["/Font"][n].get("/FontDescriptor", "")) for n in resources["/Font"])
    info = {k: v for k, v in (reader.metadata or {}).items() if v}
    assert set(info) <= {"/Title", "/CreationDate", "/ModDate", "/Trapped"} and info["/Title"] == "Curriculum vitae"
    assert info["/CreationDate"].startswith("D:2000")  # date fixe (invariant) : aucune heure de création réelle
    assert not any(reader.metadata.get(k) for k in ("/Author", "/Creator", "/Producer"))
    assert render_pdf("cv", sections(*LINES)) == pdf  # pas de date ni d'identifiant aléatoire


def test_letter_has_paragraphs_without_headings_or_dashes():
    text = words(render_pdf("cover_letter", [Section(section="Lettre", bullets=[
        Bullet(texte="Premier paragraphe.", fact_ids=[ID]), Bullet(texte="Second paragraphe.", fact_ids=[ID])])]))
    assert text == "Lettre de motivation Premier paragraphe. Second paragraphe."


def test_unsupported_characters_degrade_instead_of_breaking():
    assert latin("→ ≥ ✓ ü ñ") == "-> >= ? ü ñ"
    assert latin("abc") == "a b c"  # pas de carré ni de caractère invisible dans le texte extrait
    assert words(render_pdf("cv", sections("日本語 et français")))  # pas d'exception


def test_export_route_needs_a_green_check(alice, application, ready):
    use_model(application, GOOD)
    draft = generate(alice, ready).json()
    response = alice.get(f"/documents/{draft['id']}/pdf")
    assert response.status_code == 200 and response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == 'attachment; filename="cv.pdf"'
    assert "Stage de data analyst de 6 mois chez Acme" in words(response.content)

    lines = draft["sections"][0]["bullets"] + [{"texte": "Maîtrise de Kubernetes", "fact_ids": [], "manual": True}]
    alice.put(f"/documents/{draft['id']}", {"base_version": 1, "sections": [{"section": "Expérience", "bullets": lines}]})
    blocked = alice.get(f"/documents/{draft['id']}/pdf")
    assert blocked.status_code == 409 and blocked.json()["code"] == "check_failed"


def test_export_is_private(alice, bob, application, ready):
    use_model(application, GOOD)
    draft = generate(alice, ready).json()
    assert bob.get(f"/documents/{draft['id']}/pdf").status_code == 404
    from fastapi.testclient import TestClient
    assert TestClient(application, base_url="https://testserver").get(f"/documents/{draft['id']}/pdf").status_code == 401


@pytest.mark.parametrize("kind", ["cv", "cover_letter"])
def test_empty_document_still_renders(kind):
    assert words(render_pdf(kind, [])).startswith(("Curriculum", "Lettre"))
