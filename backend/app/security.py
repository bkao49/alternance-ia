import hashlib
import hmac
import secrets
import time
from collections.abc import Callable

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from itsdangerous import BadSignature, URLSafeTimedSerializer

_hasher = PasswordHasher()
# Hash factice : vérifié quand le compte n'existe pas, pour que le temps de réponse ne révèle rien.
_DUMMY_HASH = _hasher.hash("mot-de-passe-factice-pour-egaliser-le-temps")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(stored_hash: str | None, password: str) -> bool:
    try:
        matches = _hasher.verify(stored_hash or _DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        return False
    return matches and stored_hash is not None


def _serializer(secret: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="session-v1")


def create_session(secret: str, user_id: str) -> tuple[str, str]:
    """Retourne (jeton de session signé, identifiant de session)."""
    sid = secrets.token_urlsafe(16)
    return _serializer(secret).dumps({"u": user_id, "s": sid}), sid


def read_session(secret: str, token: str, max_age: int) -> dict | None:
    try:
        data = _serializer(secret).loads(token, max_age=max_age)
    except BadSignature:  # signature fausse, jeton modifié ou expiré
        return None
    if not isinstance(data, dict) or not isinstance(data.get("u"), str) or not isinstance(data.get("s"), str):
        return None
    return data


def csrf_token(secret: str, sid: str) -> str:
    return hmac.new(secret.encode(), f"csrf:{sid}".encode(), hashlib.sha256).hexdigest()


def csrf_is_valid(secret: str, sid: str, supplied: str | None) -> bool:
    return bool(supplied) and hmac.compare_digest(csrf_token(secret, sid), supplied)


class LoginLimiter:
    """Bloque une clé (adresse IP ou e-mail) après `max_failures` échecs dans la fenêtre.

    En mémoire : se réinitialise au redémarrage et n'est pas partagé entre processus.
    """

    def __init__(self, max_failures: int = 5, window: int = 900, clock: Callable[[], float] = time.monotonic):
        self.max_failures = max_failures
        self.window = window
        self._clock = clock
        self._failures: dict[str, list[float]] = {}

    def _recent(self, key: str) -> list[float]:
        cutoff = self._clock() - self.window
        recent = [t for t in self._failures.get(key, []) if t > cutoff]
        if recent:
            self._failures[key] = recent
        else:
            self._failures.pop(key, None)
        return recent

    def retry_after(self, key: str) -> int:
        recent = self._recent(key)
        if len(recent) < self.max_failures:
            return 0
        return int(self.window - (self._clock() - recent[0])) + 1

    def record_failure(self, key: str) -> None:
        self._recent(key)
        self._failures.setdefault(key, []).append(self._clock())

    def reset(self, key: str) -> None:
        self._failures.pop(key, None)
