import time
import logging
import threading
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)


def check_expired_commands():
    """Sprawdza co 2 sekundy czy komendy czasowe wygasły i kolejkuje TURN_OFF.

    Webapp zarządza czasem — nie Gateway. Gdy czas TURN_ON_FOR / WATER_PUMP_ON minie,
    scheduler automatycznie tworzy komendę TURN_OFF dla tego samego węzła i GPIO.
    """
    # Import wewnątrz funkcji — unikamy circular import przy starcie Django
    from .models import CentralUnit, QueuedCommand, ControllableNode

    while True:
        try:
            now = timezone.now()

            # Znajdź wszystkie dostarczone komendy czasowe, które mogły wygasnąć
            timed_commands = QueuedCommand.objects.filter(
                status=QueuedCommand.STATUS_DELIVERED,
                command__in=[QueuedCommand.COMMAND_TURN_ON_FOR, QueuedCommand.COMMAND_WATER_PUMP_ON],
                time__isnull=False,
                delivered_at__isnull=False,
            ).select_related("gateway")

            for cmd in timed_commands:
                expire_time = cmd.delivered_at + timedelta(minutes=cmd.time)
                if now < expire_time:
                    continue  # Jeszcze nie wygasła

                # Sprawdź czy TURN_OFF nie został już zakolejkowany po tej komendzie
                already_off = QueuedCommand.objects.filter(
                    gateway=cmd.gateway,
                    node_id=cmd.node_id,
                    gpio=cmd.gpio,
                    command=QueuedCommand.COMMAND_TURN_OFF,
                    created_at__gt=cmd.delivered_at,
                ).exists()

                if not already_off:
                    logger.info(
                        "Scheduler: kolejkuję TURN_OFF dla %s/%s GPIO%s "
                        "(komenda '%s' na %s min wygasła)",
                        cmd.gateway.device_id, cmd.node_id, cmd.gpio,
                        cmd.command, cmd.time,
                    )
                    QueuedCommand.objects.create(
                        gateway=cmd.gateway,
                        node_id=cmd.node_id,
                        gpio=cmd.gpio,
                        command=QueuedCommand.COMMAND_TURN_OFF,
                        status=QueuedCommand.STATUS_PENDING,
                        issued_by=cmd.issued_by,
                    )
                    ControllableNode.objects.filter(
                        gateway=cmd.gateway,
                        node_id=cmd.node_id,
                        gpio=cmd.gpio
                    ).update(is_active=False)

        except Exception as e:
            logger.error("Błąd w schedulerze: %s", e, exc_info=True)

        time.sleep(2)


def start_command_scheduler():
    logger.info("E-Cucumbers: uruchamiam scheduler komend w tle...")
    thread = threading.Thread(target=check_expired_commands, name="CommandSchedulerThread", daemon=True)
    thread.start()
