import paho.mqtt.client as mqtt
import json
import time
import os
import datetime

class Device:
    """
    Abstrakcyjna reprezentacja urządzenia kontrolowanego z poziomu Middleware.
    """
    def __init__(self, name, station):
        self.name = name
        self.station = station
        
        # Stan kontrolowanego urządzenia (aktualizowany na podstawie danych i reply)
        self.last_data = None
        self.last_seen: datetime.datetime | None = None
        self.is_sending = False
        self.delay_ms = None
        self.pins = {}

    def _send_command(self, command, arguments=None):
        """Wysyła sformatowaną komendę korzystając z MQTT stacji centralnej."""
        topic = f"/device/{self.name}/commands"
        payload = {"command": command}
        if arguments is not None:
            payload["arguments"] = arguments
            
        self.station.publish(topic, payload)

    def set_on(self):
        """Włącza wysyłanie danych z urządzenia"""
        self._send_command("set_on")

    def set_off(self):
        """Wyłącza wysyłanie danych z urządzenia"""
        self._send_command("set_off")

    def change_delay(self, delay_ms):
        """Zmienia czas między wysyłaniem wiadomości (w milisekundach)"""
        self._send_command("change_delay", delay_ms)

    def echo(self):
        """Testowa komenda sprawdzająca komunikację"""
        self._send_command("echo")

    def pin_on(self, pin):
        """Ustawia podany pin GPIO na 1"""
        self._send_command("pin_on", pin)

    def pin_off(self, pin):
        """Ustawia podany pin GPIO na 0"""
        self._send_command("pin_off", pin)

    def handle_data(self, data):
        """Aktualizuje stan na podstawie odebranych danych z MQTT (temat: .../data)"""
        self.last_data = data
        self.last_seen = datetime.datetime.now(datetime.timezone.utc)
        print(f"[Urządzenie: {self.name}] Otrzymano nowe dane: {data}")
        self._sync_to_db()

    def handle_reply(self, command, result):
        """Aktualizuje stan na podstawie odpowiedzi błędu lub sukcesu (temat: .../reply)"""
        # Możemy tu aktualizować lokalny stan urządzenia oparty na zatwierdzonych komendach
        if result == "ok":
            if command == "set_on":
                self.is_sending = True
            elif command == "set_off":
                self.is_sending = False
            self._sync_to_db()
        print(f"[Urządzenie: {self.name}] Odpowiedź na komendę '{command}': {result}")

    def _sync_to_db(self):
        """Synchronizuje bieżący stan in-memory z rekordem Node w SQLite.
        Używa bezpośrednio modułu sqlite3 — w pełni bezpieczne z wątku MQTT."""
        import sqlite3 as _sqlite3
        try:
            db_path = os.path.join(os.path.dirname(__file__), '..', 'db.sqlite3')
            db_path = os.path.abspath(db_path)

            last_seen_iso = self.last_seen.isoformat() if self.last_seen else None
            last_data_str = json.dumps(self.last_data) if self.last_data is not None else None
            pins_str = json.dumps(self.pins)

            with _sqlite3.connect(db_path) as con:
                con.execute("""
                    INSERT INTO nodes_node
                        (name, created_at, last_seen, is_sending, delay_ms, pins, last_data)
                    VALUES
                        (?, datetime('now'), ?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        last_seen    = excluded.last_seen,
                        is_sending   = excluded.is_sending,
                        delay_ms     = excluded.delay_ms,
                        pins         = excluded.pins,
                        last_data    = excluded.last_data
                """, (
                    self.name,
                    last_seen_iso,
                    1 if self.is_sending else 0,
                    self.delay_ms,
                    pins_str,
                    last_data_str,
                ))
        except Exception as e:
            print(f"[Device:{self.name}] Błąd synchronizacji z DB: {e}")

    def to_dict(self):
        """Eksportuje stan urządzenia do słownika, by zapisać do pliku JSON."""
        return {
            "name": self.name,
            "last_data": self.last_data,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "is_sending": self.is_sending,
            "delay_ms": self.delay_ms,
            "pins": self.pins,
        }

    def update_from_dict(self, data):
        """Aktualizuje stan na podstawie słownika wczytanego z pliku JSON."""
        self.last_data = data.get("last_data")
        self.is_sending = data.get("is_sending", False)
        self.delay_ms = data.get("delay_ms")
        self.pins = data.get("pins", {})
        raw_last_seen = data.get("last_seen")
        if raw_last_seen:
            try:
                self.last_seen = datetime.datetime.fromisoformat(raw_last_seen)
            except ValueError:
                self.last_seen = None


class Gateway:
    def __init__(self, broker, port, username=None, password=None):
        self.broker = broker
        self.port = port
        self.devices = {}
        self.state_file = "station.json"
        
        # Używamy najnowszego API w wersji 2
        # Jeśli na porcie 443 jest WSS (Websockets Secure), dodajemy transport
        if self.port == 443:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="Gateway", transport="websockets")
        else:
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="Gateway")
            
        if username is not None and password is not None:
            self.client.username_pw_set(username, password)
            
        if self.port in [443, 8883]:
            # Zapewnienie komunikacji bezpiecznej (TLS / SSL), która najprawdopodobniej
            # jest wymagana przy korzystaniu z portu 443 dla brokera MQTT.
            import ssl
            self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED)

        self.client.on_connect = self.on_connect
        self.client.on_disconnect = self.on_disconnect
        self.client.on_message = self.on_message
        self.client.on_publish = self.on_publish
        
        self.load_state()

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        print(f"[Gateway] Rozłączono z brokerem. Powód: {reason_code}")

    def on_publish(self, client, userdata, mid, reason_code=None, properties=None):
        print(f"[Gateway] Potwierdzenie z brokera, wiadomość wysłana pomyślnie. MID: {mid}")


    def start(self):
        """Uruchamia połączenie z brokerem MQTT i nasłuchuje zdarzeń dla stacji bazowej, a proces loop_start() przenosi obsługę nasłuchiwania w tło."""
        print(f"[Gateway] Łączenie z brokerem {self.broker}:{self.port}...")
        self.client.connect(self.broker, self.port)
        self.client.loop_start()

    def stop(self):
        """Zatrzymuje stację centralną i zapisuje stan."""
        self.save_state()
        self.client.loop_stop()
        self.client.disconnect()

    def load_state(self):
        """Wczytuje stan zarejestrowanych urządzeń na starcie jeśli plik istnieje."""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for dev_name, dev_data in data.items():
                        device = self.get_device(dev_name)
                        device.update_from_dict(dev_data)
                print(f"[Gateway] Wczytano stan {len(self.devices)} urządzeń z {self.state_file}")
            except Exception as e:
                print(f"[Gateway] Błąd ładowania stanu: {e}")

    def save_state(self):
        """Zapisuje aktualny lokalny stan znanych urządzeń do pliku JSON."""
        try:
            state = {name: dev.to_dict() for name, dev in self.devices.items()}
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=4)
            print(f"[Gateway] Zapisano stan w pliku {self.state_file}")
        except Exception as e:
            print(f"[Gateway] Błąd zapisywania stanu: {e}")

    def on_connect(self, client, userdata, flags, reason_code, properties):
        print(f"[Gateway] Połączono z brokerem (kod: {reason_code})")
        # Nasłuchujemy danych oraz odpowiedzi od WSZYSTKICH urządzeń używając wildcard '+'
        self.client.subscribe("/device/+/data")
        self.client.subscribe("/device/+/reply")
        print("[Gateway] Rozpoczęto nasłuchiwanie na /device/+/data oraz /device/+/reply")

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        
        try:
            payload_str = msg.payload.decode('utf-8')
        except UnicodeDecodeError:
            payload_str = str(msg.payload)
            
        print(f"[Gateway] Otrzymano wiadomość na temat '{topic}': {payload_str}")
        
        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError:
            print(f"[Gateway] Błąd dekodowania JSON z tematu {topic}")
            return

        # Przetwarzanie tematu w postaci: /device/NAME/msg_type
        parts = topic.split('/')
        if len(parts) >= 4 and parts[1] == "device":
            device_name = parts[2]
            msg_type = parts[3]

            # Pobranie instancji kontrolowanego urządzenia (lub zarejestrowanie na bieżąco, jeśli dotąd go nie było)
            device = self.get_device(device_name)

            if msg_type == "data":
                data_val = payload.get("data")
                device.handle_data(data_val)
            elif msg_type == "reply":
                command = payload.get("command")
                result = payload.get("result")
                device.handle_reply(command, result)

    def publish(self, topic, payload):
        """Metoda wewnętrzna dla urządzeń do wysyłania komend do brokera nakładająca enkapsulację dla klasy Device."""
        self.client.publish(topic, json.dumps(payload))
        print(f"[Gateway -> MQTT] Opublikowano na {topic}: {payload}")

    def get_device(self, name) -> Device:
        """Zwraca obiekt urządzenia, automatycznie podłączając je do lokalnego stanu, jeśli to nowo wykryte urządzenie."""
        if name not in self.devices:
            print(f"[Gateway] Wykryto/zarejestrowano urządzenie: {name}")
            self.devices[name] = Device(name, self)
        return self.devices[name]

    def add_device(self, name) -> Device:
        """Alias dla get_device - przydatny przy manualnym dodawaniu np. po kliknięciu przez użytkownika w rest API"""
        return self.get_device(name)

if __name__ == "__main__":
    import os
    USER = "user"  # Wpisz tu swoj login lub wyeksportuj w terminalu
    PASS = "ogorek123!"

    station = Gateway(broker="mqtt.krlade.dev", port=443, username=USER, password=PASS)
    ts = Device("twoja stara", station)
    
    try:
        station.start()
        
        # Trzymanie włączonego programu
        print("[Gateway] Czekam na eventy. Naciśnij Ctrl+C aby wyjść.")
        while True:
            ts._send_command("reply")
            time.sleep(2)
            
    except KeyboardInterrupt:
        print("\n[Gateway] Zatrzymywanie...")
        station.stop()
