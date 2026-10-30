"""Faux site web pour les tests des collecteurs : aucun appel réseau."""

import socket

import httpx
import pytest

from app.collectors.http_client import PoliteClient, Throttle

PUBLIC_IP = "93.184.215.14"
ROBOTS_OK = "User-agent: *\nDisallow: /prive/\n"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("appel réseau interdit dans les tests de collecteurs")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


class FakeSite:
    """Routes `chemin → (statut, en-têtes, corps)` ; garde la trace des requêtes reçues."""

    def __init__(self, routes, robots=(200, {}, ROBOTS_OK)):
        self.routes = {"/robots.txt": robots, **routes}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        status, headers, body = self.routes.get(request.url.path, (404, {}, ""))
        if callable(body):
            status, headers, body = body(request)
        content = body if isinstance(body, bytes) else body.encode()
        # Flux brut, comme un vrai serveur : le client le lit avec iter_raw().
        return httpx.Response(status, headers=headers, stream=httpx.ByteStream(content))

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]


class FakeClock:
    def __init__(self):
        self.now, self.slept = 1000.0, []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(round(seconds, 3))
        self.now += seconds


def make_client(
    site, resolver=None, clock=None, source="web_test", domains=("example.com",), **kwargs,
) -> PoliteClient:
    clock = clock or FakeClock()
    return PoliteClient(
        source, domains, transport=httpx.MockTransport(site),
        resolver=resolver or (lambda _host: [PUBLIC_IP]), throttle=Throttle(clock, clock.sleep),
        **kwargs,
    )


HTML = {"content-type": "text/html; charset=utf-8"}
