"""PDF d'un CV ou d'une lettre, fait pour être lu par les logiciels de recrutement (issue #23).

Une seule colonne, du vrai texte sélectionnable (jamais d'image), les polices standard Helvetica (rien
n'est incorporé), ni tableau, ni icône, ni lien. Les métadonnées se limitent au titre : ni auteur, ni
logiciel de création, ni date (`invariant`), donc aucune donnée personnelle ajoutée et un rendu identique
à contenu identique. Les polices standard n'ont que l'alphabet Windows-1252 : le reste est ramené à des
équivalents simples plutôt qu'à des carrés vides.
"""

import io
import unicodedata
from collections.abc import Sequence
from xml.sax.saxutils import escape

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.ai.generation.schema import Section

TITLES = {"cv": "Curriculum vitae", "cover_letter": "Lettre de motivation"}
REPLACEMENTS = str.maketrans({"→": "->", "←": "<-", "•": "-", " ": " ", " ": " ",
                              "‑": "-", "−": "-", "≤": "<=", "≥": ">="})
BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=10.5, leading=14, alignment=TA_LEFT, spaceAfter=3)
HEADING = ParagraphStyle("heading", parent=BODY, fontName="Helvetica-Bold", fontSize=12, leading=16, spaceBefore=10,
                         spaceAfter=4)
TITLE = ParagraphStyle("title", parent=BODY, fontName="Helvetica-Bold", fontSize=16, leading=20, spaceAfter=8)
ITEM = ParagraphStyle("item", parent=BODY, leftIndent=0)


def latin(value: str) -> str:
    """Texte réduit à Windows-1252 ; un caractère inconnu perd son accent ou devient « ? »."""
    value = unicodedata.normalize("NFC", value).translate(REPLACEMENTS)
    out = []
    for char in value:
        try:
            char.encode("cp1252")
            out.append(char)
        except UnicodeEncodeError:
            plain = unicodedata.normalize("NFKD", char).encode("ascii", "ignore").decode()
            out.append(plain or "?")
    return "".join(out)


def _p(value: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(latin(value)), style)


def render_pdf(kind: str, sections: Sequence[Section]) -> bytes:
    buffer = io.BytesIO()
    title = TITLES[kind]
    document = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm,
                                 bottomMargin=18 * mm, title=title, author="", subject="", creator="", producer="",
                                 invariant=1)
    story = [_p(title, TITLE)]
    for section in sections:
        if kind == "cv":
            story.append(_p(section.section, HEADING))
        for bullet in section.bullets:
            # CV : un tiret par ligne (du texte, pas un symbole) ; lettre : des paragraphes.
            story.append(_p(f"- {bullet.texte}" if kind == "cv" else bullet.texte, ITEM))
        story.append(Spacer(1, 2 * mm))
    document.build(story)
    return buffer.getvalue()
