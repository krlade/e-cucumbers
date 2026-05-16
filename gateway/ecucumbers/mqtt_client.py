import os
import atexit
from ecucumbers.core_mqtt import Gateway
from django.conf import settings

# Constants mapped from test scripts
# Global singleton
station = None

def init_mqtt():
    global station
    import sys

    # Run only in main routine or autoreload child process
    is_runserver = any(arg.endswith('runserver') for arg in sys.argv)
    if is_runserver and os.environ.get('RUN_MAIN') != 'true':
        return  # Skip initialization in the parent runserver watcher process

    if station is None:
        print("[Django MQTT] Inicjalizacja klienta obsługującego sieć sensorów...")
        try:
            station = Gateway(broker=settings.MQTT_BROKER, port=settings.MQTT_PORT, username=settings.MQTT_USER, password=settings.MQTT_PASS)
            station.start()

            # Zabezpieczenie na wyjście
            atexit.register(station.stop)
        except Exception as e:
            print(f"[Django MQTT] Nie udało się zainicjować bramki MQTT: {e}")
