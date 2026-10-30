"""Client des API officielles d'offres (Adzuna, France Travail…), ADR 0003.

Hôte fixe écrit dans le code (aucune URL venue d'une réponse n'est appelée), au moins 3 s entre
deux appels vers un même domaine (délai partagé avec le robot web), pas de redirection, corps
lu par tranches bornées et durée totale limitée, erreurs typées. Les clés passent en paramètres
ou en en-têtes : jamais dans les journaux ni dans les erreurs (ni `__cause__` ni `__context__`).
"""

import json
import logging
import re
import time
from collections.abc import Mapping
from typing import Any, Self

import httpx

from app.collectors.base import (
    InvalidResponse,
    NetworkError,
    QuotaExceeded,
    SourceBlocked,
)
from app.collectors.http_client import (
    MAX_SECONDS,
    MIN_INTERVAL,
    SHARED_THROTTLE,
    USER_AGENT,
    Throttle,
    read_body,
    retry_after,
    site_key,
)

QUERY = re.compile(r"\?[^\s\"']*")
INVALID = object()


class RedactQuery(logging.Filter):
    """httpx journalise chaque URL, paramètres compris (donc les clés) : la partie après « ? »
    est masquée, quel que soit le niveau de journal choisi plus tard."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = QUERY.sub("?…", record.getMessage())
        record.args = None
        return True


for _name in ("httpx", "httpcore"):
    _logger = logging.getLogger(_name)
    _logger.setLevel(logging.WARNING)
    if not any(isinstance(f, RedactQuery) for f in _logger.filters):
        _logger.addFilter(RedactQuery())


class ApiClient:
    def __init__(
        self,
        source: str,
        host: str,
        *,
        transport: httpx.BaseTransport | None = None,
        throttle: Throttle = SHARED_THROTTLE,
        min_interval: float = MIN_INTERVAL,
    ):
        self.source, self.host, self.throttle = source, host, throttle
        self.min_interval = max(min_interval, MIN_INTERVAL)
        self._http = httpx.Client(
            transport=transport, follow_redirects=False, trust_env=False,
            timeout=httpx.Timeout(20.0),
            headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                     "Accept-Encoding": "gzip, deflate"},
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
        host: str | None = None,
    ) -> Any:
        """JSON de la réponse (None si vide). `host` permet un second hôte fixe (OAuth2)."""
        host = host or self.host
        if not path.startswith("/"):  # « @autre-hôte » ne doit jamais changer la destination
            raise ValueError("chemin absolu attendu")
        key = site_key(host)
        self.throttle.wait(key, self.min_interval)
        failure: str | None = None
        try:
            with self._http.stream(
                method, f"https://{host}{path}", params=params, data=data, headers=headers,
            ) as response:
                status = response.status_code
                body = read_body(self.source, response, time.monotonic() + MAX_SECONDS)
                found = response.headers
        except httpx.HTTPError as exc:
            failure = type(exc).__name__  # rien d'autre : le message d'httpx contient l'URL
        finally:
            self.throttle.done(key)
        if failure is not None:
            raise NetworkError(self.source, f"échec réseau ({failure})")
        return self._parse(status, found, body)

    def _parse(self, status: int, headers: httpx.Headers, body: bytes) -> Any:
        if status in (401, 403):
            raise SourceBlocked(self.source, f"HTTP {status} : accès refusé (clé d'API ?)")
        if status == 429:
            raise QuotaExceeded(self.source, "HTTP 429", retry_after(httpx.Response(
                status, headers=headers)))
        if status >= 500:
            raise NetworkError(self.source, f"HTTP {status}")
        if not 200 <= status < 300:
            raise InvalidResponse(self.source, f"HTTP {status}")
        if status == 204 or not body:
            return None
        try:
            payload = json.loads(body)
        except (ValueError, RecursionError):
            payload = INVALID  # erreur levée hors du `except` : aucun `__context__` gardé
        if payload is INVALID:
            raise InvalidResponse(self.source, "JSON illisible")
        return payload

    def get_json(self, path: str, params: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
        return self.request_json("GET", path, params=params, **kwargs)
