"""Worker de collecte : `python -m app.worker` (processus séparé de l'API, ADR 0004).

Prend les tâches en attente une à une, lance le collecteur de la source avec les critères de
l'utilisateur et enregistre les offres sous sa RLS. Erreur réseau : nouvel essai avec délai croissant.
Blocage (403, anti-bot, CAPTCHA) : la source est arrêtée, jamais de nouvel essai ni de contournement.
"""
import contextlib
import logging
import os
import signal
import socket
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Self

from sqlalchemy import Connection, text

from app import jobs
from app.collectors.adzuna import AdzunaCollector
from app.collectors.base import (
    Collector,
    CollectResult,
    ContractType,
    NetworkError,
    QuotaExceeded,
    SearchQuery,
    SourceBlocked,
)
from app.collectors.detection import LogNotifier, Notifier
from app.collectors.expiry import mark_expired
from app.collectors.lba import LbaCollector
from app.collectors.web import WebCollector, load_sites
from app.config import WorkerSettings, get_worker_settings
from app.db import user_scope

log = logging.getLogger(__name__)

Registry = dict[str, Callable[[], Collector]]
UPSERT = text(
    "INSERT INTO job_postings (user_id, source, external_id, url, title, company, location, "
    "description_text, content_hash, contract_type, published_at, fingerprint) "
    "VALUES (:uid, :source, :external_id, :url, :title, :company, :location, :description_text, "
    ":content_hash, :contract_type, :published_at, :fingerprint) "
    # Même (source, external_id) : pas de doublon ; l'offre n'est réécrite que si son texte a changé.
    "ON CONFLICT (user_id, source, external_id) DO UPDATE SET url = EXCLUDED.url, "
    "title = EXCLUDED.title, company = EXCLUDED.company, location = EXCLUDED.location, "
    "description_text = EXCLUDED.description_text, content_hash = EXCLUDED.content_hash, "
    "contract_type = EXCLUDED.contract_type, published_at = EXCLUDED.published_at, "
    "fingerprint = EXCLUDED.fingerprint, expired = false "
    "WHERE job_postings.content_hash IS DISTINCT FROM EXCLUDED.content_hash "
    "RETURNING (xmax = 0) AS inserted"
)


def default_registry(settings: WorkerSettings) -> Registry:
    registry: Registry = {"lba": LbaCollector, "adzuna": AdzunaCollector}
    if settings.web_sites_file:
        for site in load_sites(Path(settings.web_sites_file)):
            registry[site.source] = lambda site=site: WebCollector(site)
    return registry


def load_query(conn: Connection) -> SearchQuery | None:
    """Critères de l'utilisateur courant (RLS) ; None s'il n'en a saisi aucun : on ne collecte pas
    « tout » à sa place. Seul le premier lieu est transmis (`SearchQuery` n'en prend qu'un)."""
    row = conn.execute(
        text("SELECT keywords, locations, contract_types FROM search_preferences")).first()
    if row is None or not row.keywords:
        return None
    location = row.locations[0]["label"] if row.locations else None
    return SearchQuery(keywords=tuple(row.keywords), location=location,
                       contract_types=frozenset(ContractType(c) for c in row.contract_types))


def save_offers(conn: Connection, user_id: str, result: CollectResult) -> int:
    """Enregistre les offres (clé : source + identifiant externe) ; renvoie le nombre de nouvelles."""
    new = 0
    for offer in result.offers:
        row = conn.execute(UPSERT, {
            "uid": user_id, "source": offer.source, "external_id": offer.external_id,
            "url": offer.url, "title": offer.title, "company": offer.company,
            "location": offer.location, "description_text": offer.description_text,
            "content_hash": offer.content_hash, "contract_type": offer.contract_type.value,
            "published_at": offer.published_at, "fingerprint": offer.fingerprint,
        }).first()
        new += bool(row and row.inserted)
    mark_expired(conn, result.source, result.expired)
    return new


class Heartbeat:
    """Bat toutes les `interval` secondes tant que la tâche tourne : sans battement, la tâche est
    jugée abandonnée et reprise par un autre worker."""

    def __init__(self, job: jobs.Job, worker: str, interval: float):
        self._job, self._worker, self._interval = job, worker, interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                jobs.heartbeat(self._job, self._worker)
            except Exception:  # noqa: BLE001 (une base momentanément absente ne tue pas la collecte)
                log.warning("battement non enregistré job=%s", self._job.id)

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        self._thread.join()


class Worker:
    def __init__(self, registry: Registry, settings: WorkerSettings, notifier: Notifier | None = None,
                 name: str | None = None):
        self.registry, self.settings = registry, settings
        self.notifier = notifier or LogNotifier()
        self.name = name or f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self.stop = threading.Event()

    def run_one(self) -> bool:
        """Prend et traite une tâche ; False si la file est vide."""
        job = jobs.claim_job(self.name)
        if job is None:
            return False
        with Heartbeat(job, self.name, self.settings.heartbeat_seconds):
            try:
                self._collect(job)
            except Exception as exc:  # noqa: BLE001 (une tâche en bogue ne tue pas le worker)
                # Type seulement : une trace SQL peut contenir le texte d'une annonce.
                log.error("job=%s source=%s erreur inattendue (%s)", job.id, job.source, type(exc).__name__)
                jobs.fail(job, self.name, f"erreur inattendue ({type(exc).__name__})")
        return True

    def _collect(self, job: jobs.Job) -> None:
        factory = self.registry.get(job.source)
        if factory is None:
            jobs.fail(job, self.name, "source inconnue")
            return
        with user_scope(job.user_id) as conn:
            query = load_query(conn)
        if query is None:
            jobs.succeed(job, self.name, 0, 0, 0)  # rien à chercher : aucun appel à la source
            return
        with contextlib.ExitStack() as stack:
            collector = factory()
            if hasattr(collector, "__exit__"):
                stack.enter_context(collector)
            result = collector.collect(query)
        if not jobs.heartbeat(job, self.name):  # tâche reprise par un autre worker : on n'écrit plus
            log.warning("job=%s reprise par un autre worker : résultat abandonné", job.id)
            return
        with user_scope(job.user_id) as conn:
            new = save_offers(conn, job.user_id, result)  # les offres déjà lues sont gardées
        counts = (len(result.offers), new, result.rejected)
        error = result.error
        if error is None:
            jobs.succeed(job, self.name, *counts)
        elif isinstance(error, SourceBlocked):
            log.error("job=%s source=%s bloquée : %s", job.id, job.source, error.message)
            jobs.block_source(job, self.name, error.message, counts)
            self.notifier.notify(job.source, error.message)
        elif isinstance(error, QuotaExceeded) and job.attempts >= job.max_attempts:
            # Quota toujours refusé après tous les essais : on ne harcèle pas la source (429 = blocage).
            log.error("job=%s source=%s quota persistant", job.id, job.source)
            jobs.block_source(job, self.name, "quota persistant (429)", counts)
            self.notifier.notify(job.source, "quota persistant (429)")
        elif isinstance(error, QuotaExceeded):
            jobs.retry_later(job, self.name, error.message, error.retry_after, counts)
        elif isinstance(error, NetworkError):
            jobs.retry_later(job, self.name, error.message, counts=counts)
        else:
            jobs.fail(job, self.name, error.message, counts)

    def tick(self) -> None:
        """Planifie les collectes dues et relève les tâches abandonnées."""
        created = jobs.schedule_due(self.settings.collect_interval_minutes)
        reaped = jobs.reap_stale(self.settings.stale_seconds)
        if created or reaped:
            log.info("planificateur : %d tâche(s) créée(s), %d relâchée(s)", created, reaped)

    def run_forever(self) -> None:
        log.info("worker %s démarré", self.name)
        last_tick = None
        while not self.stop.is_set():
            try:
                if last_tick is None or time.monotonic() - last_tick >= self.settings.schedule_seconds:
                    last_tick = time.monotonic()
                    self.tick()
                if not self.run_one():
                    self.stop.wait(self.settings.poll_seconds)
            except Exception as exc:  # noqa: BLE001 (base indisponible : on attend et on recommence)
                log.error("boucle du worker interrompue (%s), nouvel essai", type(exc).__name__)
                self.stop.wait(self.settings.poll_seconds)
        log.info("worker %s arrêté", self.name)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_worker_settings()
    worker = Worker(default_registry(settings), settings)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: worker.stop.set())
    worker.run_forever()


if __name__ == "__main__":
    main()
