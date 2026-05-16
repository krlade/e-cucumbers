import os
import json
import time
import threading
import ssl
import random
from dotenv import load_dotenv
import paho.mqtt.client as mqtt

# Wczytywanie konfiguracji z pliku .env, jeśli istnieje
load_dotenv()

BROKER = os.getenv("MQTT_BROKER", "mqtt.krlade.dev")
PORT = int(os.getenv("MQTT_PORT", 443))
USER = os.getenv("MQTT_USER", "user")
PASS = os.getenv("MQTT_PASS", "ogorek123!")

NODE_NAME = os.getenv("NODE_NAME", "GenericNode1")
SENSOR_PIN = 4  # Nasz testowy pin sensoryczny


class GenericNode:
    def __init__(self, name, broker, port, user, password):
        self.name = name
        self.broker = broker
        self.port = port
        
        self.is_sending = True
        self.delay_ms = 10000
        self.gpio_pins = {2: 0, 3: 0} # Symulowane piny wyjściowe GPIO
        
        # Paho MQTT - konfiguracja transportu.
        # W przypadku korzystania z portu 443 przez Cloudflare zazwyczaj wymagane jest websockets.
        transport = "websockets" if self.port == 443 else "tcp"
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{self.name}_client", transport=transport)
        
        if user and password:
            self.client.username_pw_set(user, password)
            
        if self.port in [443, 8883]:
            # Połączenie szyfrowane
            self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
            
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        # Wątek odpowiedzialny za symulowanie regularnych pomiarów
        self.worker_thread = threading.Thread(target=self._data_loop, daemon=True)

    def on_connect(self, client, userdata, flags, reason_code, properties):
        print(f"[{self.name}] Połączono z brokerem (kod: {reason_code})")
        topic_commands = f"/device/{self.name}/commands"
        self.client.subscribe(topic_commands)
        print(f"[{self.name}] Nasłuchuję komend na kanale: {topic_commands}")

    def send_reply(self, command, result, **kwargs):
        """Wysyła odpowiedź zwrotną do Gatewaya po wykonaniu komendy."""
        topic = f"/device/{self.name}/reply"
        payload = {
            "name": self.name,
            "command": command,
            "result": result
        }
        payload.update(kwargs)
        self.client.publish(topic, json.dumps(payload))
        print(f"[{self.name}] Odpowiedź ({command}): {result}")

    def on_message(self, client, userdata, msg):
        """Odbiera i parsuje komendy z Gatewaya."""
        try:
            payload = json.loads(msg.payload.decode('utf-8'))
        except json.JSONDecodeError:
            print(f"[{self.name}] Błąd dekodowania JSON z tematu {msg.topic}")
            return
            
        cmd = payload.get("command")
        args = payload.get("arguments")
        print(f"[{self.name}] Otrzymano komendę: {cmd} (args: {args})")

        if cmd == "echo":
            self.send_reply("echo", "ok")
            
        elif cmd == "set_on":
            self.is_sending = True
            self.send_reply("set_on", "ok")
            
        elif cmd == "set_off":
            self.is_sending = False
            self.send_reply("set_off", "ok")
            
        elif cmd == "change_delay":
            try:
                self.delay_ms = int(args)
                self.send_reply("change_delay", "ok")
            except (ValueError, TypeError):
                self.send_reply("change_delay", "error")
                
        elif cmd == "get_pins":
            # Zwraca listę z naszym jednym pinem sensorycznym
            self.send_reply("get_pins", f"[{SENSOR_PIN}]")
            
        elif cmd == "get_format":
            fmt = {
                "type": "float",
                "unit": "°C",
                "min": -20.0,
                "max": 60.0
            }
            self.send_reply("get_format", json.dumps(fmt))
                
        elif cmd == "pin_on":
            p = int(args)
            self.gpio_pins[p] = 1
            print(f"[{self.name}] Ustawiono pin GPIO {p} w stan WYSOKI (1)")
            self.send_reply("pin_on", "ok")
            
        elif cmd == "pin_off":
            p = int(args)
            self.gpio_pins[p] = 0
            print(f"[{self.name}] Ustawiono pin GPIO {p} w stan NISKI (0)")
            self.send_reply("pin_off", "ok")

    def _data_loop(self):
        """Pętla w tle przesyłająca sztuczne dane, gdy włączone jest wysyłanie (is_sending)."""
        while True:
            if self.is_sending:
                topic = f"/device/{self.name}/data"
                # Sztuczny pomiar z dozwolonego zakresu (od -20.0 do 60.0 °C)
                val = round(random.uniform(-20.0, 60.0), 2)
                payload = {"data": val}
                self.client.publish(topic, json.dumps(payload))
                print(f"[{self.name}] Wysyłam wartość: {val}")
                
            time.sleep(self.delay_ms / 1000.0)

    def start(self):
        print(f"[{self.name}] Łączenie z {self.broker}:{self.port}...")
        self.client.connect(self.broker, self.port)
        self.worker_thread.start()
        # Blokuje wątek główny i obsługuje pętlę MQTT
        self.client.loop_forever()


if __name__ == "__main__":
    node = GenericNode(NODE_NAME, BROKER, PORT, USER, PASS)
    try:
        node.start()
    except KeyboardInterrupt:
        print("\nPrzerwano przez użytkownika. Zakończono.")
