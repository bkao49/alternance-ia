"""Fabrique de CV fictifs pour les tests : PDF et DOCX minimaux générés ici, jamais de vrai CV."""

import io
import zipfile

CV_LINES = [
    "Camille Fictif",
    "camille.fictif@example.test",
    "06 12 34 56 78",
    "Experience",
    "Stage data analyst - Acme Fictive 2025 - 2026",
    "Analyse de ventes avec Python et SQL",
    "Formation",
    "Master Data Science - Universite Imaginaire 2024 - 2026",
    "Competences",
    "Python, SQL, Docker",
    "Langues",
    "Francais, Anglais",
]


def make_pdf(lines=CV_LINES, extra: bytes = b"") -> bytes:
    """PDF d'une page, police standard, une ligne de texte par ligne."""
    esc = lambda s: s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = "BT /F1 11 Tf 50 780 Td 14 TL " + " T* ".join(f"({esc(line)}) Tj" for line in lines) + " ET"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream.encode("latin-1") + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref) + extra
    return bytes(out)


def make_docx(lines=CV_LINES, extra: dict[str, bytes] | None = None) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in lines)
    document = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
                f'wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document)
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()
