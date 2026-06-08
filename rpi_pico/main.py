import uasyncio as asyncio
import json
import config as app_config
import network
from machine import Pin
from ws_mqtt import MQTToverWS
from network_manager import connect_wifi, load_wifi_config, ap_web_server
from leds import LedManager
from sensor import AnalogMoistureSensor
import ubinascii
import uos

# Inicjalizacja komponentów
leds = LedManager()
sensor = AnalogMoistureSensor(app_config.MOISTURE_ADC_PIN)

# Stan urządzenia
state = {
    "telemetry_active":   True,
    "telemetry_delay_ms": 5000,
    "config_mode_requested": False,
}

# Przycisk konfiguracyjny – polling
# 3.3V → przycisk → GP15, wewnętrzny pull-down: puszczony=0, wciśnięty=1
_config_button = Pin(app_config.CONFIG_BUTTON_PIN, Pin.IN, Pin.PULL_DOWN)

# Cache obiektów Pin dla komend pin_on/pin_off
_gpio_cache = {}

def get_pin(pin_id):
    if pin_id not in _gpio_cache:
        _gpio_cache[pin_id] = Pin(pin_id, Pin.OUT)
    return _gpio_cache[pin_id]

# Kolejka odebranych wiadomości MQTT
_pending_commands = []

def _on_message(topic, payload):
    _pending_commands.append((topic, payload))

global_client = None

def is_wifi_connected():
    return network.WLAN(network.STA_IF).isconnected()

async def command_listener():
    """Co 50 ms sprawdza przychodzące wiadomości MQTT i przetwarza komendy."""
    global global_client
    while True:
        if global_client is not None:
            try:
                global_client.check_msg()
            except Exception as e:
                print(f"[CMD] Utrata polaczenia: {e}")
                leds.set_status('connecting_mqtt')
                global_client = None

        while _pending_commands:
            topic, payload = _pending_commands.pop(0)
            print(f"[CMD] Odebrano na '{topic}': {payload}")
            try:
                data    = json.loads(payload.decode('utf-8'))
                command = data.get("command")
                args    = data.get("arguments")
                result  = "error"

                if command == "set_on":
                    state["telemetry_active"] = True
                    result = "ok"

                elif command == "set_off":
                    state["telemetry_active"] = False
                    result = "ok"

                elif command == "change_delay":
                    try:
                        new_delay = int(args)
                        if new_delay >= 100:
                            state["telemetry_delay_ms"] = new_delay
                            result = "ok"
                    except (ValueError, TypeError):
                        pass

                elif command == "echo":
                    result = "ok"

                elif command == "pin_on":
                    try:
                        pin_id = int(args)
                        if pin_id in app_config.ALLOWED_PINS:
                            get_pin(pin_id).on()
                            result = "ok"
                        else:
                            print(f"[CMD] pin_on: pin {pin_id} nie jest dozwolony")
                    except (ValueError, TypeError):
                        pass

                elif command == "pin_off":
                    try:
                        pin_id = int(args)
                        if pin_id in app_config.ALLOWED_PINS:
                            get_pin(pin_id).off()
                            result = "ok"
                        else:
                            print(f"[CMD] pin_off: pin {pin_id} nie jest dozwolony")
                    except (ValueError, TypeError):
                        pass

                elif command == "get_pins":
                    try:
                        result = str(app_config.ALLOWED_PINS)
                    except Exception:
                        result = "error"

                elif command == "get_format":
                    try:
                        result = app_config.SENSOR_FORMAT
                    except Exception:
                        result = "error"

                if global_client:
                    reply_topic   = f"/device/{app_config.NAME}/reply"
                    reply_payload = json.dumps({
                        "name":    app_config.NAME,
                        "command": command,
                        "result":  result
                    })
                    try:
                        global_client.publish(reply_topic, reply_payload)
                        print(f"[CMD] Wyslano odpowiedz: {reply_payload}")
                    except Exception as e:
                        print(f"[CMD] Blad publish reply: {e}")

            except Exception as e:
                print("[CMD] Blad przetwarzania komendy:", e)

        await asyncio.sleep_ms(50)

async def telemetry_loop():
    """Pętla pomiarowa: Wi-Fi, MQTT, telemetria, obsługa przycisku."""
    global global_client
    while True:
        # Sprawdzenie przycisku konfiguracyjnego
        if state["config_mode_requested"]:
            state["config_mode_requested"] = False
            print("[Config] Przycisk wcisniety – uruchamianie trybu AP...")
            if global_client:
                try:
                    global_client.disconnect()
                except Exception:
                    pass
                global_client = None
            leds.set_status('no_wifi')
            await ap_web_server()
            return

        # Sprawdzenie Wi-Fi
        if not is_wifi_connected():
            print("[Telemetria] Brak Wi-Fi. Proba ponowienia...")
            leds.set_status('no_wifi')
            global_client = None
            ok = await connect_wifi(leds)
            if not ok:
                await asyncio.sleep_ms(10000)
                continue

        # (Re)połączenie z brokerem MQTT
        if global_client is None:
            leds.set_status('connecting_mqtt')
            cfg       = load_wifi_config()
            broker    = cfg.get("mqtt_broker",   app_config.MQTT_BROKER)
            port      = int(cfg.get("mqtt_port", app_config.MQTT_PORT))
            mqtt_user = cfg.get("mqtt_user",     app_config.MQTT_USER)
            mqtt_pass = cfg.get("mqtt_password", app_config.MQTT_PASSWORD)

            client_id = f"{app_config.NAME}-" + ubinascii.hexlify(uos.urandom(4)).decode()
            client = MQTToverWS(
                host=broker, port=port, path="/",
                client_id=client_id,
                user=mqtt_user, password=mqtt_pass,
                keepalive=60
            )
            client.set_callback(_on_message)
            try:
                print("[Telemetria] Laczenie z brokerem WS...")
                client.connect()
                command_topic = f"/device/{app_config.NAME}/commands"
                client.subscribe(command_topic)
                print(f"[Telemetria] Polaczono! Subskrypcja: {command_topic}")
                global_client = client
                leds.set_status('connected')
            except Exception as e:
                print(f"[Telemetria] Blad polaczenia: {e}")
                await asyncio.sleep_ms(5000)
                continue

        # Wysyłanie danych
        if state["telemetry_active"] and global_client is not None:
            try:
                val = await sensor.read()
                payload = json.dumps({
                    "name": app_config.NAME,
                    "data": val
                })
                telemetry_topic = f"/device/{app_config.NAME}/data"
                global_client.publish(telemetry_topic, payload)
                print(f"[Telemetria] Wyslano: {payload}")
            except Exception as e:
                print(f"[Telemetria] Blad wysylania: {e}")
                global_client = None
                continue

        await asyncio.sleep_ms(state["telemetry_delay_ms"])

async def button_watcher():
    """Odpytuje przycisk co 50 ms. Wciśnięcie (GP15==1) ustawia flagę trybu AP."""
    while True:
        if _config_button.value() == 1:
            print("[Button] Przycisk wcisniety – zaplanowano tryb AP.")
            state["config_mode_requested"] = True
            while _config_button.value() == 1:
                await asyncio.sleep_ms(50)
        await asyncio.sleep_ms(50)

async def main():
    asyncio.create_task(leds.run())
    asyncio.create_task(button_watcher())

    wifi_ok = await connect_wifi(leds)
    if not wifi_ok:
        print("[Main] Brak Wi-Fi. Wcisnij przycisk aby skonfigurowac.")

    asyncio.create_task(command_listener())
    await telemetry_loop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Przerwano przez uzytkownika.")
    except Exception as e:
        print("Blad krytyczny programu:", e)
