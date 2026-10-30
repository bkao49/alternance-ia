"""Client HTTP poli et sûr pour les collecteurs qui lisent des sites web (#59, #40).

- liste blanche de domaines, http(s) sur le port par défaut, adresses non publiques refusées,
  y compris après une redirection (SSRF) ;
- `robots.txt` lu et respecté (RFC 9309), User-Agent identifiable ;
- au plus une requête toutes les 3 s par domaine (ou le `Crawl-delay` s'il est plus long) ;
- cache : une URL déjà lue n'est pas relue ; sinon revalidation par ETag / Last-Modified ;
- 401, 403, 407 et 429 arrêtent la source : aucun contournement.
"""

import ipaddress
import logging
import socket
import time
import urllib.robotparser
from collections.abc import Callable, Iterable, MutableMapping
from dataclasses import dataclass, field
from typing import Self
from urllib.parse import urljoin, urlsplit

import httpx

from app.collectors.base import (
    CollectorError,
    InvalidResponse,
    NetworkError,
    QuotaExceeded,
    SourceBlocked,
    canonical_url,
)

log = logging.getLogger(__name__)

ROBOTS_AGENT = "alternance-ia-bot"
USER_AGENT = f"{ROBOTS_AGENT}/0.1 (+https://github.com/bkao49/alternance-ia)"
MIN_INTERVAL = 3.0  # secondes entre deux requêtes vers un même domaine
MAX_CRAWL_DELAY = 60.0  # au-delà, le site ne veut pas de robot : on n'insiste pas
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 5
REDIRECTS = {301, 302, 303, 307, 308}
BLOCKING = {401, 403, 407}

Resolver = Callable[[str], Iterable[str]]


def system_resolver(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)]


def is_public_address(address: str) -> bool:
    """Faux pour les adresses locales, privées, de lien local (169.254.169.254), réservées…"""
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class UnsafeUrl(CollectorError):
    """URL invalide, hors liste blanche ou menant à une adresse non publique : refusée."""


class RobotsDisallowed(CollectorError):
    """Le `robots.txt` du site interdit cette page : elle est ignorée."""


class PageNotFound(CollectorError):
    """404 ou 410 : la page n'existe plus (annonce retirée)."""


@dataclass(frozen=True)
class Page:
    url: str  # URL finale, après redirections
    status: int
    text: str
    content_type: str
    headers: dict[str, str] = field(default_factory=dict)  # noms en minuscules


@dataclass
class CachedPage:
    page: Page
    etag: str | None = None
    last_modified: str | None = None


class PoliteClient:
    """Un client par source. `cache` peut être partagé d'une collecte à l'autre."""

    def __init__(
        self,
        source: str,
        allowed_domains: Iterable[str],
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: Resolver = system_resolver,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        min_interval: float = MIN_INTERVAL,
        cache: MutableMapping[str, CachedPage] | None = None,
    ):
        self.source = source
        self.allowed = tuple(d.strip().strip(".").lower() for d in allowed_domains)
        if not self.allowed or any(_is_ip(d) or not d for d in self.allowed):
            raise ValueError("liste de domaines vide ou contenant une adresse IP")
        self.resolver, self.clock, self.sleep = resolver, clock, sleep
        self.min_interval = min_interval
        self.cache = cache if cache is not None else {}
        self._read: set[str] = set()  # URL déjà lues pendant cette collecte
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._crawl_delay: dict[str, float] = {}
        self._last: dict[str, float] = {}
        # trust_env=False : ni proxy ni identifiants .netrc lus depuis l'environnement.
        self._http = httpx.Client(
            transport=transport, follow_redirects=False, trust_env=False,
            timeout=httpx.Timeout(15.0), headers={"User-Agent": USER_AGENT},
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self._http.close()

    # --- Vérifications ----------------------------------------------------------------------

    def _domain(self, host: str) -> str | None:
        return next((d for d in self.allowed if host == d or host.endswith("." + d)), None)

    def check_url(self, url: str) -> str:
        """URL canonique si elle est sûre ; sinon `UnsafeUrl`. Appelée avant chaque requête."""
        try:
            url = canonical_url(url)
        except ValueError as exc:
            raise UnsafeUrl(self.source, "URL invalide") from exc
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.port is not None:
            raise UnsafeUrl(self.source, "port non standard refusé")
        if self._domain(host) is None:
            raise UnsafeUrl(self.source, "domaine hors liste blanche")
        try:
            addresses = list(self.resolver(host))
        except OSError as exc:
            raise NetworkError(self.source, "résolution DNS impossible") from exc
        if not addresses or not all(is_public_address(a) for a in addresses):
            raise UnsafeUrl(self.source, "adresse non publique refusée")
        return url

    # --- Requêtes ---------------------------------------------------------------------------

    def get(self, url: str) -> Page:
        """Page HTML ou texte, après `robots.txt`, délai par domaine et redirections vérifiées."""
        url = self.check_url(url)
        cached = self.cache.get(url)
        if cached and url in self._read:
            return cached.page
        response, final_url = self._follow(url, check_robots=True, cached=cached)
        status = response.status_code
        if status == 304 and cached:
            self._read.add(url)
            return cached.page
        self._raise_for_status(response)
        page = Page(
            url=final_url, status=status, text=response.text,
            content_type=response.headers.get("content-type", "").split(";")[0].strip().lower(),
            headers={k.lower(): v for k, v in response.headers.items()},
        )
        self.cache[url] = CachedPage(
            page, response.headers.get("etag"), response.headers.get("last-modified"),
        )
        self._read.add(url)
        return page

    def _follow(
        self, url: str, *, check_robots: bool, cached: CachedPage | None = None,
    ) -> tuple[httpx.Response, str]:
        for _ in range(MAX_REDIRECTS + 1):
            if check_robots and not self._allowed_by_robots(url):
                raise RobotsDisallowed(self.source, "page interdite par robots.txt")
            response = self._send(url, cached)
            if response.status_code not in REDIRECTS:
                return response, url
            location = response.headers.get("location")
            if not location:
                raise InvalidResponse(self.source, "redirection sans destination")
            url, cached = self.check_url(urljoin(url, location)), None
        raise InvalidResponse(self.source, "trop de redirections")

    def _send(self, url: str, cached: CachedPage | None = None) -> httpx.Response:
        domain = self._domain(urlsplit(url).hostname or "") or ""
        self._wait(domain)
        headers = {}
        if cached and cached.etag:
            headers["If-None-Match"] = cached.etag
        if cached and cached.last_modified:
            headers["If-Modified-Since"] = cached.last_modified
        try:
            with self._http.stream("GET", url, headers=headers) as response:
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise InvalidResponse(self.source, "page trop volumineuse")
                return httpx.Response(
                    response.status_code, headers=response.headers, content=bytes(body),
                    request=response.request,
                )
        except httpx.HTTPError as exc:
            raise NetworkError(self.source, f"échec réseau ({type(exc).__name__})") from exc
        finally:
            self._last[domain] = self.clock()

    def _wait(self, domain: str) -> None:
        delay = max(self.min_interval, self._crawl_delay.get(domain, 0.0))
        last = self._last.get(domain)
        if last is not None and (remaining := last + delay - self.clock()) > 0:
            self.sleep(remaining)

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if 200 <= status < 300:
            return
        if status in BLOCKING:
            raise SourceBlocked(self.source, f"HTTP {status}")
        if status == 429:
            raise QuotaExceeded(self.source, "HTTP 429", _retry_after(response))
        if status in (404, 410):
            raise PageNotFound(self.source, f"HTTP {status}")
        if status >= 500:
            raise NetworkError(self.source, f"HTTP {status}")
        raise InvalidResponse(self.source, f"HTTP {status}")

    # --- robots.txt -------------------------------------------------------------------------

    def _allowed_by_robots(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        parser = self._robots.get(origin)
        if parser is None:
            parser = self._robots[origin] = self._load_robots(origin)
        return parser.can_fetch(ROBOTS_AGENT, url)

    def _load_robots(self, origin: str) -> urllib.robotparser.RobotFileParser:
        """RFC 9309 : 4xx = aucune règle ; 5xx ou panne = tout interdit (on réessaiera plus
        tard). Par prudence, 401, 403 et 429 sur robots.txt arrêtent la source."""
        response, _ = self._follow(origin + "/robots.txt", check_robots=False)
        status = response.status_code
        parser = urllib.robotparser.RobotFileParser()
        if 200 <= status < 300:
            parser.parse(response.text.splitlines())
        elif status in BLOCKING or status == 429 or status >= 500:
            self._raise_for_status(response)
        else:
            parser.parse([])
        delay = parser.crawl_delay(ROBOTS_AGENT)
        if delay is not None:
            if float(delay) > MAX_CRAWL_DELAY:
                raise CollectorError(self.source, "Crawl-delay trop long : site ignoré")
            domain = self._domain(urlsplit(origin).hostname or "") or ""
            self._crawl_delay[domain] = max(self._crawl_delay.get(domain, 0.0), float(delay))
        return parser


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip("[]"))
    except ValueError:
        return False
    return True


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after", "")
    return float(value) if value.isdigit() else None
