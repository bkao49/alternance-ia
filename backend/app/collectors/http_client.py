"""Client HTTP poli et sûr pour les collecteurs qui lisent des sites web (#59, #40, ADR 0003).

- liste blanche de domaines, http(s) sur le port par défaut, adresses non publiques refusées,
  y compris après une redirection (SSRF) ;
- `robots.txt` lu et respecté (RFC 9309), User-Agent identifiable ;
- au plus une requête toutes les 3 s par domaine, partagé entre toutes les sources (ou le
  `Crawl-delay` s'il est plus long) ;
- cache : une URL déjà lue n'est pas relue ; sinon revalidation par ETag / Last-Modified ;
- 401, 403, 407, 429 et défi anti-bot déclaré arrêtent la source : aucun contournement.
"""

import datetime as dt
import email.utils
import ipaddress
import logging
import socket
import threading
import time
import urllib.robotparser
import zlib
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
from app.collectors.detection import block_cause

log = logging.getLogger(__name__)

ROBOTS_AGENT = "alternance-ia-bot"
USER_AGENT = f"{ROBOTS_AGENT}/0.1 (+https://github.com/bkao49/alternance-ia)"
MIN_INTERVAL = 3.0  # secondes entre deux requêtes vers un même domaine (plancher)
MAX_CRAWL_DELAY = 60.0  # au-delà, le site ne veut pas de robot : on n'insiste pas
MAX_BYTES = 2_000_000  # après décompression
MAX_SECONDS = 30.0  # durée totale d'une requête
MAX_REDIRECTS = 5
MAX_CACHE = 5000
REDIRECTS = {301, 302, 303, 307, 308}
HTML_TYPES = {"text/html", "application/xhtml+xml"}
BLOCKING = {401, 403, 407}
KEPT_HEADERS = {"content-type", "etag", "last-modified", "retry-after", "server", "cf-mitigated"}
# Préfixes IPv6 qui transportent une adresse IPv4 (NAT64, 6to4, Teredo) : refusés en bloc.
EMBEDDED_IPV4 = [ipaddress.ip_network(n) for n in
                 ("64:ff9b::/96", "64:ff9b:1::/48", "2002::/16", "2001::/32")]

Resolver = Callable[[str], Iterable[str]]


def system_resolver(host: str) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)]


def is_public_address(address: str) -> bool:
    """Faux pour les adresses locales, privées, de lien local (169.254.169.254), réservées…"""
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif any(ip in net for net in EMBEDDED_IPV4):
            return False
    return ip.is_global and not ip.is_multicast


def site_key(host: str) -> str:
    """Clé du délai par domaine : les deux derniers labels (`jobs.example.com` → `example.com`).
    Volontairement large : deux sites qui partagent la clé attendent l'un pour l'autre."""
    return ".".join(host.split(".")[-2:])


class PageSkipped(CollectorError):
    """Problème propre à une page : elle est ignorée, la collecte de la source continue."""


class UnsafeUrl(PageSkipped):
    """URL invalide, hors liste blanche ou menant à une adresse non publique : refusée."""


class RobotsDisallowed(PageSkipped):
    """Le `robots.txt` du site interdit cette page."""


class PageNotFound(PageSkipped):
    """404 ou 410 : la page n'existe plus (annonce retirée)."""


class PageTooLarge(PageSkipped):
    """Page de plus de MAX_BYTES, une fois décompressée."""


@dataclass(frozen=True)
class Page:
    url: str  # URL finale, après redirections
    status: int
    text: str
    content_type: str
    headers: dict[str, str] = field(default_factory=dict)  # KEPT_HEADERS, noms en minuscules


@dataclass
class CachedPage:
    page: Page
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True)
class RawResponse:
    status: int
    headers: dict[str, str]  # noms en minuscules
    body: bytes

    @property
    def text(self) -> str:
        charset = "utf-8"
        for part in self.headers.get("content-type", "").split(";")[1:]:
            key, _, value = part.strip().partition("=")
            if key.lower() == "charset" and value:
                charset = value.strip("\"' ")
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


class Throttle:
    """Dernière requête par domaine. Une instance partagée par défaut entre toutes les sources."""

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.clock, self.sleep = clock, sleep
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, key: str, delay: float) -> None:
        with self._lock:
            last = self._last.get(key)
            if last is not None and (remaining := last + delay - self.clock()) > 0:
                self.sleep(remaining)
            self._last[key] = self.clock()

    def done(self, key: str) -> None:
        with self._lock:
            self._last[key] = self.clock()


SHARED_THROTTLE = Throttle()


class PoliteClient:
    """Un client par source. `cache` peut être partagé d'une collecte à l'autre."""

    def __init__(
        self,
        source: str,
        allowed_domains: Iterable[str],
        *,
        transport: httpx.BaseTransport | None = None,
        resolver: Resolver = system_resolver,
        throttle: Throttle = SHARED_THROTTLE,
        min_interval: float = MIN_INTERVAL,
        cache: MutableMapping[str, CachedPage] | None = None,
    ):
        self.source = source
        self.allowed = tuple(d.strip().strip(".").lower() for d in allowed_domains)
        if not self.allowed or any(_is_ip(d) or not d for d in self.allowed):
            raise ValueError("liste de domaines vide ou contenant une adresse IP")
        self.resolver, self.throttle = resolver, throttle
        self.min_interval = max(min_interval, MIN_INTERVAL)  # jamais moins de 3 s
        self.cache = cache if cache is not None else {}
        self._read: set[str] = set()  # URL déjà lues pendant cette collecte
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        self._refused: set[str] = set()  # origines dont le Crawl-delay est trop long
        self._crawl_delay: dict[str, float] = {}
        # trust_env=False : ni proxy ni identifiants .netrc lus depuis l'environnement.
        self._http = httpx.Client(
            transport=transport, follow_redirects=False, trust_env=False,
            timeout=httpx.Timeout(15.0),
            headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip, deflate"},
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    # --- Vérifications ----------------------------------------------------------------------

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
        if not any(host == d or host.endswith("." + d) for d in self.allowed):
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
        self._read.add(url)
        if response.status == 304 and cached:
            return cached.page
        self._raise_for_status(response)
        headers = {k: v for k, v in response.headers.items() if k in KEPT_HEADERS}
        page = Page(
            url=final_url, status=response.status, text=response.text, headers=headers,
            content_type=headers.get("content-type", "").split(";")[0].strip().lower(),
        )
        # Défi anti-bot, CAPTCHA ou page de connexion servis en 200 (#14) : on s'arrête.
        if page.content_type in HTML_TYPES and (cause := block_cause(page.text, final_url, url)):
            raise SourceBlocked(self.source, cause)
        self.cache[url] = CachedPage(page, headers.get("etag"), headers.get("last-modified"))
        while len(self.cache) > MAX_CACHE:  # les plus anciennes entrées partent d'abord
            del self.cache[next(iter(self.cache))]
        return page

    def _follow(
        self, url: str, *, check_robots: bool, cached: CachedPage | None = None,
    ) -> tuple[RawResponse, str]:
        for _ in range(MAX_REDIRECTS + 1):
            if check_robots and not self._allowed_by_robots(url):
                raise RobotsDisallowed(self.source, "page interdite par robots.txt")
            response = self._send(url, cached)
            if response.status not in REDIRECTS:
                return response, url
            location = response.headers.get("location")
            if not location:
                raise InvalidResponse(self.source, "redirection sans destination")
            target = self.check_url(urljoin(url, location))
            if url.startswith("https:") and not target.startswith("https:"):
                raise UnsafeUrl(self.source, "redirection de https vers http refusée")
            url, cached = target, None
        raise PageSkipped(self.source, "trop de redirections")

    def _send(self, url: str, cached: CachedPage | None = None) -> RawResponse:
        key = site_key(urlsplit(url).hostname or "")
        self.throttle.wait(key, max(self.min_interval, self._crawl_delay.get(key, 0.0)))
        headers = {}
        if cached and cached.etag:
            headers["If-None-Match"] = cached.etag
        if cached and cached.last_modified:
            headers["If-Modified-Since"] = cached.last_modified
        deadline = time.monotonic() + MAX_SECONDS
        try:
            with self._http.stream("GET", url, headers=headers) as response:
                found = {k.lower(): v for k, v in response.headers.items()}
                body = read_body(self.source, response, deadline)
                return RawResponse(response.status_code, found, body)
        except httpx.HTTPError as exc:
            raise NetworkError(self.source, f"échec réseau ({type(exc).__name__})") from exc
        finally:
            self.throttle.done(key)

    def _raise_for_status(self, response: RawResponse) -> None:
        status = response.status
        if response.headers.get("cf-mitigated", "").lower() == "challenge":
            raise SourceBlocked(self.source, "défi anti-bot")
        if 200 <= status < 300:
            return
        if status in BLOCKING:
            raise SourceBlocked(self.source, f"HTTP {status}")
        if status == 429:
            raise QuotaExceeded(self.source, "HTTP 429", retry_after(response))
        if status in (404, 410):
            raise PageNotFound(self.source, f"HTTP {status}")
        if status >= 500:
            raise NetworkError(self.source, f"HTTP {status}")
        raise InvalidResponse(self.source, f"HTTP {status}")

    # --- robots.txt -------------------------------------------------------------------------

    def _allowed_by_robots(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._refused:
            raise CollectorError(self.source, "Crawl-delay trop long : site ignoré")
        parser = self._robots.get(origin)
        if parser is None:
            parser = self._robots[origin] = self._load_robots(origin)
        return parser.can_fetch(ROBOTS_AGENT, url)

    def _load_robots(self, origin: str) -> urllib.robotparser.RobotFileParser:
        """RFC 9309 : 4xx = aucune règle ; 5xx, panne ou réponse inattendue = tout interdit
        (on réessaiera plus tard). Par prudence, 401, 403 et 429 arrêtent la source."""
        response, _ = self._follow(origin + "/robots.txt", check_robots=False)
        status = response.status
        parser = urllib.robotparser.RobotFileParser()
        if response.headers.get("cf-mitigated", "").lower() == "challenge":
            self._raise_for_status(response)
        if 200 <= status < 300:
            parser.parse(response.text.splitlines())
        elif 400 <= status < 500 and status not in BLOCKING and status != 429:
            parser.parse([])
        else:
            self._raise_for_status(response)
            raise InvalidResponse(self.source, f"robots.txt : HTTP {status}")
        delay = parser.crawl_delay(ROBOTS_AGENT)
        if delay is not None:
            if float(delay) > MAX_CRAWL_DELAY:
                self._refused.add(origin)
                raise CollectorError(self.source, "Crawl-delay trop long : site ignoré")
            key = site_key(urlsplit(origin).hostname or "")
            self._crawl_delay[key] = max(self._crawl_delay.get(key, 0.0), float(delay))
        return parser


def read_body(
    source: str, response: httpx.Response, deadline: float, max_bytes: int = MAX_BYTES,
) -> bytes:
    """Corps décompressé par tranches bornées : une « bombe » gzip ne dépasse pas MAX_BYTES.
    Partagé par `PoliteClient` et `ApiClient` (ADR 0003). Lève aussi au-delà de `deadline`."""
    length = response.headers.get("content-length", "")
    if length.isdigit() and int(length) > max_bytes:
        raise PageTooLarge(source, "page trop volumineuse")
    encoding = response.headers.get("content-encoding", "").strip().lower()
    if encoding not in ("", "identity", "gzip", "x-gzip", "deflate"):
        raise InvalidResponse(source, "compression non prise en charge")
    inflater = zlib.decompressobj(47) if encoding not in ("", "identity") else None
    body = bytearray()
    for chunk in response.iter_raw():
        if time.monotonic() > deadline:
            raise NetworkError(source, "délai total dépassé")
        try:
            data = inflater.decompress(chunk, max_bytes + 1 - len(body)) if inflater else chunk
        except zlib.error as exc:
            raise InvalidResponse(source, "compression illisible") from exc
        body.extend(data)
        if len(body) > max_bytes or (inflater and inflater.unconsumed_tail):
            raise PageTooLarge(source, "page trop volumineuse")
    return bytes(body)


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip("[]"))
    except ValueError:
        return False
    return True


def retry_after(response: RawResponse | httpx.Response) -> float | None:
    value = response.headers.get("retry-after", "").strip()
    if value.isdigit():
        return float(value)
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.UTC)
    return max(0.0, (when - dt.datetime.now(dt.UTC)).total_seconds())
