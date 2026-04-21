import os
import atexit
from ecucumbers.core_mqtt import Gateway

# Constants mapped from test scripts
MQTT_BROKER = "mqtt.krlade.dev"
MQTT_PORT = 443
MQTT_USER = "user"
MQTT_PASS = "ogorek123!"

# Global singleton
station = None

def init_mqtt():
    global station
    import sys
    
    # Run only in main routine or autoreload child process
    is_runserver = any(arg.endswith('runserver') for arg in sys.argv)
    if is_runserver and os.environ.get('RUN_MAIN') != 'true':
        return # Skip initialization in the parent runserver watcher process

    if station is None:
        print("[Django MQTT] Inicjalizacja klienta obsługującego sieć sensorów...")
        try:
            # Assuming the station.json file should be relative to BASE_DIR
            from django.conf import settings
            station = Gateway(broker=MQTT_BROKER, port=MQTT_PORT, username=MQTT_USER, password=MQTT_PASS)
            # Overwrite state_file path
            station.state_file = os.path.join(settings.BASE_DIR, "station.json")
            station.load_state()
            station.start()
            
            # Zabezpieczenie na wyjście
            atexit.register(station.stop)
        except Exception as e:
            print(f"[Django MQTT] Nie udało się zainicjować bramki MQTT: {e}")
