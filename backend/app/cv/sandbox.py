"""Lance l'extraction dans un processus séparé, sans secret, avec un délai maximal.

Le processus fils reçoit un environnement vide (ni DATABASE_URL ni SECRET_KEY), un dossier de travail
temporaire vide et le fichier sur son entrée standard. Il est lancé en mode isolé (`-I`) : ni variable
PYTHONPATH, ni dossier courant dans le chemin d'import. Le texte lu n'est jamais journalisé.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

WORKER = Path(__file__).with_name("extract_worker.py")
TIMEOUT_SECONDS = 20
MAX_OUTPUT = 400_000  # octets de texte acceptés en retour
ERRORS = {"encrypted", "too_many_pages", "no_text", "unreadable"}


class ExtractionFailed(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def extract_text(data: bytes, file_type: str) -> str:
    env = {k: v for k, v in os.environ.items() if k == "SYSTEMROOT"}  # Windows l'exige, rien d'autre
    with tempfile.TemporaryDirectory() as workdir:
        try:
            done = subprocess.run(
                [sys.executable, "-I", str(WORKER), file_type],
                input=data, capture_output=True, timeout=TIMEOUT_SECONDS, cwd=workdir, env=env, check=False,
            )
        except subprocess.TimeoutExpired:
            raise ExtractionFailed("timeout") from None
    if done.returncode == 0 and len(done.stdout) <= MAX_OUTPUT:
        return done.stdout.decode("utf-8", "replace")
    code = done.stderr[:40].decode("ascii", "ignore")
    raise ExtractionFailed(code if done.returncode == 3 and code in ERRORS else "unreadable")
