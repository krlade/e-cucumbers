import time
import logging
import threading
from datetime import timedelta
from django.utils import timezone

logger = logging.getLogger(__name__)

def check_expired_commands():
    # Import inside to prevent circular dependency issues during django startup
    from .models import ControllableNode, QueuedCommand

    while True:
        try:
            now = timezone.now()
            # Find peripherals that can be controlled (have peripheral_type and gpio set)
            peripherals = ControllableNode.objects.filter(
                peripheral_type__isnull=False,
                gpio__isnull=False
            )
            
            for peripheral in peripherals:
                # Find the latest delivered command for this peripheral
                latest_cmd = QueuedCommand.objects.filter(
                    peripheral=peripheral,
                    status=QueuedCommand.STATUS_DELIVERED
                ).order_by("-delivered_at").first()
                
                # If the latest command is a timed turn-on command:
                if (
                    latest_cmd 
                    and latest_cmd.command in ["TURN_ON_FOR", "WATER_PUMP_ON"] 
                    and latest_cmd.time 
                    and latest_cmd.delivered_at
                ):
                    expire_time = latest_cmd.delivered_at + timedelta(minutes=latest_cmd.time)
                    if now >= expire_time:
                        # Check if a TURN_OFF command has already been created/queued since this command was delivered
                        has_turn_off = QueuedCommand.objects.filter(
                            peripheral=peripheral,
                            command="TURN_OFF",
                            created_at__gt=latest_cmd.delivered_at
                        ).exists()
                        
                        if not has_turn_off:
                            logger.info(
                                f"Scheduler auto-queuing TURN_OFF for peripheral {peripheral} "
                                f"(timed command '{latest_cmd.command}' with duration {latest_cmd.time}m expired)"
                            )
                            # Create a pending TURN_OFF command
                            QueuedCommand.objects.create(
                                peripheral=peripheral,
                                command="TURN_OFF",
                                status=QueuedCommand.STATUS_PENDING,
                                issued_by=latest_cmd.issued_by
                            )
        except Exception as e:
            logger.error(f"Error in background scheduler: {e}", exc_info=True)
            
        time.sleep(2)

def start_command_scheduler():
    logger.info("Starting E-Cucumbers background command scheduler...")
    thread = threading.Thread(target=check_expired_commands, name="CommandSchedulerThread", daemon=True)
    thread.start()
