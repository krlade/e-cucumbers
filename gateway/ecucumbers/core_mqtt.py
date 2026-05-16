import paho.mqtt.client as mqtt
import json
import time
import os
import datetime

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'db.sqlite3'))


class Device:
    """
    Abstrakcyjna reprezentacja urządzenia kontrolowanego z poziomu Middleware.
    """

    # Opis formatu danych pomiarowych wysyłanych przez urządzenie.
    # Wartości min/max mogą być nadpisane przy rejestracji urządzenia.
    FORMAT = {
        "type": "float",
        "min": None,
        "max": None,
        "unit": "",
    }

    def __init__(self, name, station):
        self.name = name
        self.station = station

        # Stan kontrolowanego urządzenia (aktualizowany na podstawie danych i reply)
        self.last_data = None
        self.last_seen: datetime.datetime | None = None
        self.is_sending = False
        self.delay_ms = None
        self.pins = {}
        
        # Pojedynczy pin sensoryczny i jego wartości
        self.sensor_pin = None
        self.sensor_type = None
        self.sensor_unit = None
        self.sensor_min_value = None
        self.sensor_max_value = None
        self.sensor_last_value = None
        self.has_format = False
        self.logs_history = []

    def _add_log(self, msg):
        """Dodaje log do lokalnej historii urządzenia oraz wypisuje na konsolę."""
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {msg}"
        self.logs_history.append(log_entry)
        if len(self.logs_history) > 100:
            self.logs_history.pop(0)
        print(f"[Urządzenie: {self.name}] {msg}")

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

    def get_pins(self):
        """Wysyła komendę get_pins do urządzenia — urządzenie odpowie listą
        dostępnych pinów GPIO przez temat .../reply."""
        self._send_command("get_pins")

    def get_format(self):
        """Wysyła komendę get_format do urządzenia —
        urządzenie odpowie opisem formatu danych pomiarowych przez temat .../reply."""
        self._send_command("get_format")

    def handle_data(self, data):
        """Aktualizuje stan na podstawie odebranych danych z MQTT (temat: .../data).
        Jeśli data jest słownikiem z kluczami będącymi numerami pinów,
        aktualizuje pojedynczy pin pomiarowy węzła."""
        self.last_data = data
        self.last_seen = datetime.datetime.now(datetime.timezone.utc)
        if isinstance(data, dict):
            for k, v in data.items():
                if self.sensor_pin is None:
                    self.sensor_pin = int(k)
                self.sensor_last_value = v
                break # Zakładamy jeden pin pomiarowy
        elif data is not None:
            self.sensor_last_value = data
        self._add_log(f"Otrzymano nowe dane: {data}")
        self._sync_to_db()

    def handle_reply(self, command, result, pin_arg=None):
        """Aktualizuje stan na podstawie odpowiedzi (temat: .../reply)"""
        if command == "get_pins":
            try:
                import ast
                import sqlite3 as _sqlite3
                pins_list = ast.literal_eval(str(result))
                if pins_list:
                    p = int(pins_list[0]) # Bierzemy tylko pierwszy jako sensor
                    if self.sensor_pin != p:
                        self.sensor_pin = p
                    self._sync_to_db()
                    self._add_log("Auto get_format()")
                    self.get_format()
                    
                    with _sqlite3.connect(DB_PATH) as con:
                        node_id_row = con.execute("SELECT id FROM nodes_node WHERE name = ?", (self.name,)).fetchone()
                        if node_id_row:
                            node_id = node_id_row[0]
                            for switch_pin in pins_list[1:]:
                                con.execute("""
                                    INSERT INTO nodes_switch (node_id, switch_id, state, switch_type)
                                    VALUES (?, ?, 0, 'LAMP')
                                    ON CONFLICT(node_id, switch_id) DO NOTHING
                                """, (node_id, int(switch_pin)))
            except Exception as e:
                self._add_log(f"Błąd parsowania get_pins: {e}")

        elif command == "get_format":
            fmt = None
            if isinstance(result, dict):
                fmt = result
            elif isinstance(result, str):
                try:
                    fmt = json.loads(result)
                except json.JSONDecodeError:
                    pass
            if fmt is not None:
                self.sensor_type = fmt.get("type")
                self.sensor_unit = fmt.get("unit")
                self.sensor_min_value = fmt.get("min")
                self.sensor_max_value = fmt.get("max")
                self.has_format = True
                self._sync_to_db()

        elif result == "ok":
            if command == "set_on":
                self.is_sending = True
            elif command == "set_off":
                self.is_sending = False
            self._sync_to_db()

        self._add_log(f"Odpowiedź na komendę '{command}': {result}")

    def _sync_to_db(self):
        """Synchronizuje bieżący stan in-memory z rekordem Node w SQLite.
        Używa bezpośrednio modułu sqlite3 — w pełni bezpieczne z wątku MQTT."""
        import sqlite3 as _sqlite3
        try:
            last_seen_iso = self.last_seen.isoformat() if self.last_seen else None
            last_data_str = json.dumps(self.last_data) if self.last_data is not None else None
            pins_str = json.dumps(self.pins)
            val_str = str(self.sensor_last_value) if self.sensor_last_value is not None else None
            logs_str = json.dumps(self.logs_history)

            with _sqlite3.connect(DB_PATH) as con:
                con.execute("""
                    INSERT INTO nodes_node
                        (name, created_at, last_seen, is_sending, delay_ms, pins, last_data,
                         sensor_pin, sensor_type, sensor_unit, sensor_min_value, sensor_max_value, sensor_last_value, logs)
                    VALUES
                        (?, datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name) DO UPDATE SET
                        last_seen    = excluded.last_seen,
                        is_sending   = excluded.is_sending,
                        delay_ms     = excluded.delay_ms,
                        pins         = excluded.pins,
                        last_data    = excluded.last_data,
                        sensor_pin   = excluded.sensor_pin,
                        sensor_type  = excluded.sensor_type,
                        sensor_unit  = excluded.sensor_unit,
                        sensor_min_value = excluded.sensor_min_value,
                        sensor_max_value = excluded.sensor_max_value,
                        sensor_last_value = excluded.sensor_last_value,
                        logs         = excluded.logs
                """, (
                    self.name,
                    last_seen_iso,
                    1 if self.is_sending else 0,
                    self.delay_ms,
                    pins_str,
                    last_data_str,
                    self.sensor_pin,
                    self.sensor_type,
                    self.sensor_unit,
                    self.sensor_min_value,
                    self.sensor_max_value,
                    val_str,
                    logs_str,
                ))

        except Exception as e:
            self._add_log(f"Błąd synchronizacji z DB: {e}")


class Gateway:
    def __init__(self, broker, port, username=None, password=None):
        self.broker = broker
        self.port = port
        self.devices = {}

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

        self._load_from_db()

    def on_disconnect(self, client, userdata, disconnect_flags, reason_code, properties):
        print(f"[Gateway] Rozłączono z brokerem. Powód: {reason_code}")

    def on_publish(self, client, userdata, mid, reason_code=None, properties=None):
        print(f"[Gateway] Potwierdzenie z brokera, wiadomość wysłana pomyślnie. MID: {mid}")

    def start(self):
        """Uruchamia połączenie z brokerem MQTT i nasłuchuje zdarzeń dla stacji bazowej,
        a proces loop_start() przenosi obsługę nasłuchiwania w tło."""
        print(f"[Gateway] Łączenie z brokerem {self.broker}:{self.port}...")
        self.client.connect(self.broker, self.port)
        self.client.loop_start()

    def stop(self):
        """Zatrzymuje stację centralną. Stan jest już na bieżąco zapisany w SQLite."""
        self.client.loop_stop()
        self.client.disconnect()

    def _load_from_db(self):
        """Wczytuje stan wszystkich węzłów z tabeli nodes_node w SQLite na starcie."""
        import sqlite3 as _sqlite3
        try:
            with _sqlite3.connect(DB_PATH) as con:
                con.row_factory = _sqlite3.Row
                # Sprawdź które opcjonalne kolumny istnieją (migracja mogła nie być jeszcze zastosowana)
                cols = {r[1] for r in con.execute("PRAGMA table_info(nodes_node)").fetchall()}
                select_cols = "id, name, last_data, last_seen, is_sending, delay_ms, pins"
                
                # Upewniamy się czy mamy te kolumny
                if "sensor_pin" in cols:
                    select_cols += ", sensor_pin, sensor_type, sensor_unit, sensor_min_value, sensor_max_value, sensor_last_value"
                if "logs" in cols:
                    select_cols += ", logs"
                
                rows = con.execute(f"SELECT {select_cols} FROM nodes_node").fetchall()

            for row in rows:
                device = self.get_device(row["name"])
                # last_data
                raw_ld = row["last_data"]
                try:
                    device.last_data = json.loads(raw_ld) if raw_ld is not None else None
                except (json.JSONDecodeError, TypeError):
                    device.last_data = raw_ld
                # last_seen
                raw_ls = row["last_seen"]
                if raw_ls:
                    try:
                        device.last_seen = datetime.datetime.fromisoformat(raw_ls)
                    except ValueError:
                        device.last_seen = None
                # pozostałe pola
                device.is_sending = bool(row["is_sending"])
                device.delay_ms = row["delay_ms"]
                raw_pins = row["pins"]
                try:
                    device.pins = json.loads(raw_pins) if raw_pins else {}
                except (json.JSONDecodeError, TypeError):
                    device.pins = {}

                if "sensor_pin" in cols:
                    device.sensor_pin = row["sensor_pin"]
                    device.sensor_type = row["sensor_type"]
                    device.sensor_unit = row["sensor_unit"]
                    device.sensor_min_value = row["sensor_min_value"]
                    device.sensor_max_value = row["sensor_max_value"]
                    
                    raw_val = row["sensor_last_value"]
                    try:
                        if raw_val is not None:
                            v = float(raw_val)
                            if v.is_integer(): v = int(v)
                            device.sensor_last_value = v
                        else:
                            device.sensor_last_value = None
                    except (ValueError, TypeError):
                        device.sensor_last_value = raw_val

                    device.has_format = any(x is not None for x in [device.sensor_type, device.sensor_unit, device.sensor_min_value, device.sensor_max_value])

                if "logs" in cols:
                    raw_logs = row["logs"]
                    try:
                        device.logs_history = json.loads(raw_logs) if raw_logs else []
                    except (json.JSONDecodeError, TypeError):
                        device.logs_history = []

            print(f"[Gateway] Wczytano stan {len(self.devices)} urządzeń z SQLite.")
        except Exception as e:
            print(f"[Gateway] Błąd ładowania stanu z SQLite: {e}")

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

            # Pobranie instancji kontrolowanego urządzenia (lub zarejestrowanie na bieżąco)
            device = self.get_device(device_name)

            if msg_type == "data":
                data_val = payload.get("data")
                device.handle_data(data_val)
            elif msg_type == "reply":
                command = payload.get("command")
                result = payload.get("result")
                # pin_arg dla get_format — numer pinu, którego format dotyczy
                pin_arg = payload.get("pin")
                device.handle_reply(command, result, pin_arg=pin_arg)

    def publish(self, topic, payload):
        """Metoda wewnętrzna dla urządzeń do wysyłania komend do brokera."""
        self.client.publish(topic, json.dumps(payload))
        print(f"[Gateway -> MQTT] Opublikowano na {topic}: {payload}")

    def get_device(self, name) -> Device:
        """Zwraca obiekt urządzenia, automatycznie podłączając je do lokalnego stanu,
        jeśli to nowo wykryte urządzenie."""
        if name not in self.devices:
            print(f"[Gateway] Wykryto/zarejestrowano urządzenie: {name}")
            self.devices[name] = Device(name, self)
        return self.devices[name]

    def add_device(self, name) -> Device:
        """Alias dla get_device - przydatny przy manualnym dodawaniu przez REST API."""
        return self.get_device(name)


if __name__ == "__main__":
    USER = "user"  # Wpisz tu swoj login lub wyeksportuj w terminalu
    PASS = "ogorek123!"

    station = Gateway(broker="mqtt.krlade.dev", port=443, username=USER, password=PASS)
    ts = Device("twoja stara", station)

    try:
        station.start()

        print("[Gateway] Czekam na eventy. Naciśnij Ctrl+C aby wyjść.")
        while True:
            ts._send_command("reply")
            time.sleep(2)

    except KeyboardInterrupt:
        print("\n[Gateway] Zatrzymywanie...")
        station.stop()
