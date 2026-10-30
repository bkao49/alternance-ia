"""Contrôles d'un fichier déposé, sans jamais l'ouvrir avec un analyseur : octets seulement.

Le type se décide sur le contenu (signature), jamais sur l'extension ni sur le type annoncé.
Le nom d'origine n'est gardé que pour l'affichage : il n'est jamais utilisé comme chemin.
"""

import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass

MAX_BYTES = 5 * 1024 * 1024
MAX_NAME = 120
# Limites d'un DOCX : un CV réel dépasse rarement quelques centaines de Ko décompressés.
MAX_ZIP_ENTRIES = 200
MAX_UNZIPPED_BYTES = 20 * 1024 * 1024
MAX_ZIP_RATIO = 100
# Marqueurs de PDF « actifs » (script, lancement, fichier embarqué) : refusés sans rien exécuter.
PDF_ACTIVE = re.compile(rb"/(?:JavaScript|JS|Launch|EmbeddedFile|RichMedia|OpenAction|AA|Encrypt)\b")
MACRO_PARTS = ("vbaproject.bin", "vbadata.xml", "activex/", "embeddings/")
MIME = {"pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


class Rejected(Exception):
    """Fichier refusé ; `reason` est un code stable, jamais un morceau du contenu."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Checked:
    file_type: str  # "pdf" | "docx"
    name: str


def clean_name(raw: str | None) -> str:
    """Nom d'affichage : dernier segment, sans caractère de contrôle, 120 caractères au plus."""
    name = (raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in unicodedata.normalize("NFC", name) if c.isprintable()).strip()
    return name[:MAX_NAME] or "cv"


def check_file(data: bytes, raw_name: str | None) -> Checked:
    if not data:
        raise Rejected("empty")
    if len(data) > MAX_BYTES:
        raise Rejected("too_large")
    if data.startswith(b"%PDF-"):
        if PDF_ACTIVE.search(data):
            raise Rejected("active_content")
        return Checked("pdf", clean_name(raw_name))
    if data.startswith(b"PK\x03\x04"):
        _check_docx(data)
        return Checked("docx", clean_name(raw_name))
    raise Rejected("type")


def _check_docx(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise Rejected("zip_entries")
            names = {i.filename.lower() for i in infos}
            if not {"[content_types].xml", "word/document.xml"} <= names:
                raise Rejected("type")
            total = sum(i.file_size for i in infos)
            if total > MAX_UNZIPPED_BYTES or total > MAX_ZIP_RATIO * len(data):
                raise Rejected("zip_bomb")
            for name in names:
                if name.startswith("/") or ".." in name.split("/") or "\\" in name:
                    raise Rejected("zip_path")
                if any(part in name for part in MACRO_PARTS):
                    raise Rejected("active_content")
    except zipfile.BadZipFile:
        raise Rejected("type") from None
