"""Extraction du texte d'un CV, lancée dans un processus à part par `sandbox.py`.

Ce script n'importe rien de l'application (ni configuration, ni base, ni secret) : il lit le fichier
sur l'entrée standard, écrit le texte sur la sortie standard. Le fichier n'est jamais exécuté, jamais
écrit sur le disque. Le réseau est coupé dans le processus, la mémoire et le temps processeur limités.
Code de sortie 0 : texte sur la sortie standard. Code 3 : échec propre, code d'erreur sur la sortie
d'erreur. Tout autre code : plantage.
"""

import io
import socket
import sys
import zipfile
from xml.etree import ElementTree

MAX_PAGES = 30
MAX_CHARS = 100_000
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _no_network() -> None:
    def refuse(*_args, **_kwargs):
        raise OSError("réseau désactivé")

    socket.socket = refuse  # type: ignore[misc,assignment]
    socket.create_connection = refuse  # type: ignore[assignment]
    socket.getaddrinfo = refuse  # type: ignore[assignment]


def _limits() -> None:
    try:
        import resource
    except ImportError:  # Windows : seuls les garde-fous du processus parent s'appliquent
        return
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))  # aucune écriture de fichier
    resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))


def fail(code: str) -> None:
    sys.stderr.write(code)
    sys.exit(3)


def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            fail("encrypted")
        if len(reader.pages) > MAX_PAGES:
            fail("too_many_pages")
        out, size = [], 0
        for page in reader.pages:
            chunk = page.extract_text() or ""
            out.append(chunk)
            size += len(chunk)
            if size > MAX_CHARS:
                break
        return "\n".join(out)
    except (PyPdfError, ValueError, KeyError, TypeError, RecursionError, OSError, AttributeError):
        fail("unreadable")
    return ""


def docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml")
        if xml[:2] in (b"\xff\xfe", b"\xfe\xff") or b"\x00" in xml[:8]:  # UTF-16 : contrôles suivants aveugles
            fail("unreadable")
        if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():  # pas d'entités : bombes XML
            fail("unreadable")
        root = ElementTree.fromstring(xml)
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, ValueError, RecursionError):
        fail("unreadable")
    lines = []
    for paragraph in root.iter(f"{W}p"):
        lines.append("".join(
            (node.text or "") if node.tag == f"{W}t" else "\t" if node.tag == f"{W}tab" else ""
            for node in paragraph.iter()))
    return "\n".join(lines)


def main() -> None:
    kind = sys.argv[1] if len(sys.argv) == 2 else ""
    if kind not in ("pdf", "docx"):
        fail("unreadable")
    _no_network()
    _limits()
    data = sys.stdin.buffer.read()
    text = pdf_text(data) if kind == "pdf" else docx_text(data)
    text = text.replace("\x00", "")[:MAX_CHARS]
    if not text.strip():
        fail("no_text")
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
