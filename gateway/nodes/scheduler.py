"""
nodes/scheduler.py
------------------
Menedżer harmonogramów MQTT oparty na APScheduler.
Zarządza cyklicznym wykonywaniem komend zdefiniowanych w modelu ScheduledCommand.
"""
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

# Singleton schedulera
_scheduler: BackgroundScheduler | None = None


def _job_id(sc_id: int) -> str:
    return f"scheduled_cmd_{sc_id}"


def _execute_command(sc_id: int):
    """Callback wykonywany przez APScheduler — pobiera rekord z DB i wysyła komendę."""
    try:
        from nodes.models import ScheduledCommand, SCHEDULABLE_COMMANDS_INT_ARG
        from ecucumbers.mqtt_client import station

        sc = ScheduledCommand.objects.get(pk=sc_id)
        if not sc.enabled:
            return

        if station is None or sc.node_name not in station.devices:
            logger.warning("[Scheduler] Brak live device dla '%s' — pomijam komendę '%s'.",
                           sc.node_name, sc.command)
            return

        device = station.devices[sc.node_name]
        method = getattr(device, sc.command, None)
        if method is None:
            logger.error("[Scheduler] Nieznana metoda '%s' na Device.", sc.command)
            return

        if sc.command in SCHEDULABLE_COMMANDS_INT_ARG:
            if sc.argument is None:
                logger.error("[Scheduler] Komenda '%s' wymaga argumentu int — brak wartości.", sc.command)
                return
            method(sc.argument)
        else:
            method()

        # Aktualizacja znacznika czasu ostatniego uruchomienia
        ScheduledCommand.objects.filter(pk=sc_id).update(
            last_run=datetime.now(timezone.utc)
        )
        logger.info("[Scheduler] Wykonano: %s", sc)
    except Exception as exc:
        logger.exception("[Scheduler] Błąd podczas wykonywania zadania sc_id=%d: %s", sc_id, exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone="UTC")
    return _scheduler


def init_scheduler():
    """Uruchamia scheduler i ładuje wszystkie aktywne harmonogramy z bazy."""
    sched = get_scheduler()
    if sched.running:
        return

    sched.start()
    logger.info("[Scheduler] Uruchomiono APScheduler.")

    try:
        from django.db import connection
        table_names = connection.introspection.table_names()
        if "nodes_scheduledcommand" not in table_names:
            logger.warning("[Scheduler] Tabela nodes_scheduledcommand nie istnieje jeszcze — pomijam ładowanie zadań.")
            return

        from nodes.models import ScheduledCommand
        active = ScheduledCommand.objects.filter(enabled=True)
        for sc in active:
            _add_job(sc)
        logger.info("[Scheduler] Załadowano %d aktywnych zadań.", active.count())
    except Exception as exc:
        logger.exception("[Scheduler] Błąd ładowania zadań z bazy: %s", exc)


def shutdown_scheduler():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[Scheduler] Zatrzymano APScheduler.")


def _add_job(sc):
    sched = get_scheduler()
    job_id = _job_id(sc.pk)
    if sched.get_job(job_id):
        sched.remove_job(job_id)
    sched.add_job(
        _execute_command,
        trigger=IntervalTrigger(seconds=sc.interval_seconds),
        id=job_id,
        args=[sc.pk],
        replace_existing=True,
        misfire_grace_time=30,
    )
    logger.info("[Scheduler] Dodano zadanie: %s (co %ds)", sc, sc.interval_seconds)


def add_or_replace(sc):
    """Dodaje lub zastępuje zadanie schedulera dla podanego ScheduledCommand."""
    if sc.enabled:
        _add_job(sc)
    else:
        remove(sc.pk)


def remove(sc_id: int):
    """Usuwa zadanie schedulera dla podanego ID."""
    sched = get_scheduler()
    job_id = _job_id(sc_id)
    if sched.get_job(job_id):
        sched.remove_job(job_id)
        logger.info("[Scheduler] Usunięto zadanie sc_id=%d.", sc_id)


def toggle(sc_id: int, enabled: bool):
    """Włącza lub wyłącza zadanie bez usuwania rekordu z bazy."""
    from nodes.models import ScheduledCommand
    sc = ScheduledCommand.objects.get(pk=sc_id)
    sc.enabled = enabled
    sc.save(update_fields=["enabled"])
    if enabled:
        _add_job(sc)
    else:
        remove(sc_id)
