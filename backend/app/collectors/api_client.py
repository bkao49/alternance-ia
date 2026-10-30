"""Client des API officielles d'offres (Adzuna, France Travail…).

Hôte fixe écrit dans le code (aucune URL venue d'une réponse n'est appelée), au moins 3 s entre
deux appels vers un même hôte, pas de redirection, erreurs typées. Les clés passent en
paramètres ou en en-têtes : jamais dans les journaux ni dans les messages d'erreur.
"""

import logging
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
    MAX_BYTES,
    MIN_INTERVAL,
    SHARED_THROTTLE,
    USER_AGENT,
    Throttle,
    _retry_after,
)

log = logging.getLogger(__name__)
# httpx journalise chaque URL au niveau INFO, paramètres compris : les clés d'API y seraient.
logging.getLogger("httpx").setLevel(logging.WARNING)


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
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
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
        """JSON de la réponse. `host` permet un second hôte fixe (serveur OAuth2)."""
        host = host or self.host
        self.throttle.wait(host, self.min_interval)
        try:
            response = self._http.request(
                method, f"https://{host}{path}", params=params, data=data, headers=headers,
            )
        except httpx.HTTPError as exc:
            # Le type seulement : le message d'httpx contient l'URL, donc les clés.
            raise NetworkError(self.source, f"échec réseau ({type(exc).__name__})") from None
        finally:
            self.throttle.done(host)
        status = response.status_code
        if status in (401, 403):
            raise SourceBlocked(self.source, f"HTTP {status} : accès refusé (clé d'API ?)")
        if status == 429:
            raise QuotaExceeded(self.source, "HTTP 429", _retry_after(response))
        if status >= 500:
            raise NetworkError(self.source, f"HTTP {status}")
        if not 200 <= status < 300:
            raise InvalidResponse(self.source, f"HTTP {status}")
        if status == 204 or not response.content:
            return None
        if len(response.content) > MAX_BYTES:
            raise InvalidResponse(self.source, "réponse trop volumineuse")
        try:
            return response.json()
        except (ValueError, RecursionError):
            raise InvalidResponse(self.source, "JSON illisible") from None

    def get_json(self, path: str, params: Mapping[str, Any] | None = None, **kwargs: Any) -> Any:
        return self.request_json("GET", path, params=params, **kwargs)
