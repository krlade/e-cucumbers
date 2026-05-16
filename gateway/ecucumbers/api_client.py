"""
ecucumbers/api_client.py
------------------------
Klient HTTP do komunikacji Gateway ↔ API.

Odpowiada za:
  - Jednorazową rejestrację gateway'a (POST /api/nodes/register-device/) z tokenem parowania
  - Cykliczny heartbeat (POST /api/nodes/heartbeat/) z JWT gatewaya
  - Odbiór zakolejkowanych komend i ich wykonanie przez MQTT
  - Automatyczne odświeżanie tokenu JWT (refresh)
"""
import json
import logging
import os
import threading
import time
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

# Ścieżka do pliku z tokenami JWT gatewaya (access + refresh)
_TOKEN_FILE = os.path.join(os.path.dirname(__file__), '..', '.gateway_tokens.json')
_TOKEN_FILE = os.path.abspath(_TOKEN_FILE)

# Singleton stanu
_heartbeat_thread: threading.Thread | None = None
_stop_event = threading.Event()

# Stan połączenia (dostępny dla widoków)
status = {
    "paired": False,
    "device_id": None,
    "last_heartbeat": None,
    "last_error": None,
    "api_url": None,
}


# ---------------------------------------------------------------------------
# Narzędzia HTTP
# ---------------------------------------------------------------------------

def _api_url() -> str:
    from django.conf import settings
    return getattr(settings, "API_BASE_URL", "http://localhost:3002").rstrip("/")


def _post(path: str, body: dict, token: str | None = None) -> dict:
    """Wykonuje POST do API i zwraca sparsowany JSON."""
    url = _api_url() + path
    data = json.dumps(body).encode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_bytes = e.read()
        try:
            detail = json.loads(body_bytes)
        except Exception:
            detail = body_bytes.decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Błąd sieci/połączenia: {e.reason}") from e


# ---------------------------------------------------------------------------
# Tokeny JWT
# ---------------------------------------------------------------------------

def _load_tokens() -> dict | None:
    """Wczytuje tokeny JWT z pliku lokalnego."""
    if not os.path.exists(_TOKEN_FILE):
        return None
    try:
        with open(_TOKEN_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return None


def _save_tokens(tokens: dict):
    """Zapisuje tokeny JWT do pliku lokalnego."""
    try:
        with open(_TOKEN_FILE, "w") as f:
            json.dump(tokens, f)
    except Exception as e:
        logger.error("[ApiClient] Nie można zapisać tokenów: %s", e)


def _refresh_access_token(refresh_token: str) -> str | None:
    """Odświeża access token. Zwraca nowy access token lub None."""
    try:
        result = _post("/api/token/refresh/", {"refresh": refresh_token})
        return result.get("access")
    except Exception as e:
        logger.warning("[ApiClient] Refresh tokenu nieudany: %s", e)
        return None


def _get_valid_access_token() -> str | None:
    """
    Zwraca ważny access token.
    Próbuje odświeżyć jeśli access wygasł.
    Zwraca None jeśli nie ma tokenów lub refresh też jest nieważny.
    """
    tokens = _load_tokens()
    if not tokens:
        return None

    access = tokens.get("access")
    refresh = tokens.get("refresh")

    if not access:
        return None

    # Sprawdź czy access token jeszcze działa (pingiem heartbeata)
    # Jeśli 401 — próbuj refresh
    return access  # Zakładamy ważny; heartbeat wykryje 401 i odświeży


# ---------------------------------------------------------------------------
# Rejestracja (jednorazowa)
# ---------------------------------------------------------------------------

def register(pairing_token: str, device_id: str) -> dict:
    """
    Rejestruje gateway w API za pomocą tokenu parowania.
    Zwraca dict z 'access' i 'refresh' lub rzuca RuntimeError.
    """
    logger.info("[ApiClient] Rejestracja device_id=%s ...", device_id)
    result = _post("/api/nodes/register-device/", {
        "device_id": device_id,
        "pairing_token": pairing_token,
    })
    tokens = {"access": result["access"], "refresh": result["refresh"]}
    _save_tokens(tokens)
    status["paired"] = True
    status["device_id"] = device_id
    status["last_error"] = None
    logger.info("[ApiClient] Zarejestrowano pomyślnie. device_id=%s", device_id)
    return result


# ---------------------------------------------------------------------------
# Heartbeat + wykonanie komend
# ---------------------------------------------------------------------------

def _execute_command(cmd: dict):
    """Wykonuje komendę odebraną z API przez lokalny MQTT gateway."""
    try:
        from ecucumbers.mqtt_client import station

        command_name = cmd.get("command")
        node_id = cmd.get("peripheral", {}).get("node_id")
        gpio = cmd.get("peripheral", {}).get("gpio")
        time_param = cmd.get("time")

        if station is None or node_id not in station.devices:
            logger.warning("[ApiClient] Brak live device dla '%s' — pomijam komendę '%s'.",
                           node_id, command_name)
            return

        device = station.devices[node_id]

        # Mapowanie komend API → metody Device
        if command_name == "TURN_ON":
            device.pin_on(gpio)
        elif command_name == "TURN_OFF":
            device.pin_off(gpio)
        elif command_name == "TURN_ON_FOR":
            # Włącz na `time` minut — pin_on + zaplanuj wyłączenie
            device.pin_on(gpio)
            if time_param:
                def _delayed_off():
                    time.sleep(time_param * 60)
                    device.pin_off(gpio)
                threading.Thread(target=_delayed_off, daemon=True).start()
        elif command_name == "WATER_PUMP_ON":
            device.pin_on(gpio)
            if time_param:
                def _delayed_pump_off():
                    time.sleep(time_param * 60)
                    device.pin_off(gpio)
                threading.Thread(target=_delayed_pump_off, daemon=True).start()
        else:
            logger.warning("[ApiClient] Nieznana komenda: %s", command_name)

        logger.info("[ApiClient] Wykonano: %s -> %s GPIO%s", command_name, node_id, gpio)
    except Exception as e:
        logger.exception("[ApiClient] Błąd wykonania komendy: %s", e)


def _heartbeat_once() -> bool:
    """
    Jeden cykl heartbeat: pobiera komendy z API i je wykonuje.
    Zwraca True jeśli sukces, False jeśli błąd autoryzacji (trzeba refresh).
    """
    tokens = _load_tokens()
    if not tokens:
        return False

    access = tokens.get("access")
    refresh = tokens.get("refresh")

    try:
        result = _post("/api/nodes/heartbeat/", {}, token=access)
        status["last_heartbeat"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        status["last_error"] = None

        commands = result.get("commands", [])
        if commands:
            logger.info("[ApiClient] Heartbeat: %d komend do wykonania.", len(commands))
            for cmd in commands:
                _execute_command(cmd)

        return True

    except RuntimeError as e:
        err_str = str(e)
        if "401" in err_str:
            # Spróbuj refresh
            logger.info("[ApiClient] Access token wygasł — próba odświeżenia.")
            new_access = _refresh_access_token(refresh)
            if new_access:
                tokens["access"] = new_access
                _save_tokens(tokens)
                logger.info("[ApiClient] Token odświeżony pomyślnie.")
                return True
            else:
                status["paired"] = False
                status["last_error"] = "Refresh token nieważny — wymagane ponowne parowanie."
                logger.error("[ApiClient] Refresh nieudany. Wymagane ponowne parowanie.")
                return False
        else:
            status["last_error"] = err_str
            logger.warning("[ApiClient] Heartbeat błąd: %s", err_str)
            return False


# ---------------------------------------------------------------------------
# Wątek heartbeat
# ---------------------------------------------------------------------------

def _heartbeat_loop(interval_seconds: int):
    logger.info("[ApiClient] Uruchomiono heartbeat co %ds.", interval_seconds)
    while not _stop_event.is_set():
        try:
            _heartbeat_once()
        except Exception as e:
            logger.exception("[ApiClient] Nieoczekiwany błąd w pętli heartbeat: %s", e)
        _stop_event.wait(interval_seconds)
    logger.info("[ApiClient] Wątek heartbeat zatrzymany.")


def init_api_client():
    """
    Inicjalizuje klienta API:
    - Sprawdza czy gateway jest sparowany (tokeny istnieją)
    - Uruchamia wątek heartbeat jeśli sparowany
    """
    global _heartbeat_thread

    from django.conf import settings
    interval = getattr(settings, "API_HEARTBEAT_INTERVAL", 30)
    status["api_url"] = _api_url()

    tokens = _load_tokens()
    if tokens:
        status["paired"] = True
        logger.info("[ApiClient] Znaleziono tokeny — gateway jest sparowany. Uruchamiam heartbeat.")
    else:
        logger.info("[ApiClient] Brak tokenów — gateway nie jest sparowany. Wywołaj register().")

    _stop_event.clear()
    _heartbeat_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(interval,),
        daemon=True,
        name="ApiHeartbeat",
    )
    _heartbeat_thread.start()


def shutdown_api_client():
    """Zatrzymuje wątek heartbeat."""
    _stop_event.set()
    if _heartbeat_thread and _heartbeat_thread.is_alive():
        _heartbeat_thread.join(timeout=5)
    logger.info("[ApiClient] Zatrzymano.")
