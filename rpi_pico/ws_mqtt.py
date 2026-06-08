"""
ws_mqtt.py – Klient MQTT 3.1.1 over WebSocket dla projektu IoT.

Moduł realizuje minimalną, ale pełną implementację protokołu MQTT 3.1.1
tunelowanego przez ramki binarne WebSocket (opcode 0x02), zgodnie
z wymaganiami dokumentacji projektu (sekcja 2.1 – TRANSPORT MQTT).

Architektura:
    Warstwa transportu składa się z trzech poziomów:
    1. TCP/TLS socket  – połączenie z brokerem (port 443, Cloudflare)
    2. WebSocket        – tunelowanie ramek binarnych (RFC 6455)
    3. MQTT 3.1.1       – protokół komunikacyjny (CONNECT, PUBLISH, …)

Tryb pracy:
    Metoda connect() jest SYNCHRONICZNA (blokuje na czas handshake'u).
    Metoda check_msg() jest NIEBLOKUJĄCA (socket timeout=0).
    Obie są wywoływane z korutyn uasyncio w main.py, co zapewnia
    współbieżność z innymi zadaniami (LED, pomiary, komendy).

    UWAGA: MicroPython na Pico W nie wspiera asyncio StreamReader/Writer
    z surowym SSL socketem, dlatego używamy synchronicznych socketów
    z timeout=0 zamiast natywnego async I/O.

Kompatybilność z brokerem:
    Moduł jest przetestowany z brokerem za Cloudflare (wss://mqtt.krlade.dev:443).
    Kluczowe elementy kompatybilności:
    - ssl.CERT_NONE      – Pico W nie posiada trust store z certyfikatami CA
    - Sec-WebSocket-Protocol: mqtt  – wymagany przez serwer proxy
    - User-Agent: MicroPython/PicoW – identyfikacja klienta

Użycie (z poziomu main.py):
    client = MQTToverWS(
        host="mqtt.krlade.dev", port=443, path="/",
        client_id="PICO-abc123",
        user="user", password="ogorek123!"
    )
    client.set_callback(on_message_fn)
    client.connect()           # synchroniczne, blokuje ~1-2s
    client.subscribe("/device/PICO/commands")
    client.publish("/device/PICO/data", '{"name":"PICO","data":0.5}')
    client.check_msg()         # nieblokujące, wywoływać w pętli co ~50ms
    client.disconnect()
"""

import socket
import ssl
import struct
import ubinascii
import uos
import time


# ================================================================
#  Warstwa 1: Kompatybilność socketów MicroPython
# ================================================================
# MicroPython po opakowaniu socketu w SSL zmienia API:
# - sock.send()  →  ssl_sock.write()
# - sock.recv()  →  ssl_sock.read()
# Poniższe helpery ujednolicają interfejs.

def _sock_send(sock, data):
    """Wysyła dane przez socket (zwykły lub SSL)."""
    if hasattr(sock, "write"):
        return sock.write(data)
    return sock.send(data)


def _sock_recv(sock, n):
    """Odbiera do n bajtów z socketu (zwykły lub SSL).

    Zwraca b"" zamiast rzucać wyjątkiem przy braku danych
    na sockecie nieblokującym (EAGAIN/ETIMEDOUT).
    """
    try:
        if hasattr(sock, "read"):
            res = sock.read(n)
            return res if res is not None else b""
        return sock.recv(n)
    except OSError as e:
        if e.args[0] in (11, 110):  # 11=EAGAIN, 110=ETIMEDOUT
            return b""
        raise


def _sock_settimeout(sock, t):
    """Ustawia timeout socketu (kompatybilnie z SSL wrapperem)."""
    if hasattr(sock, "settimeout"):
        sock.settimeout(t)
    elif hasattr(sock, "setblocking"):
        sock.setblocking(t != 0)


def _recv_exact(sock, n):
    """Odbiera dokładnie n bajtów. Rzuca OSError przy zamknięciu."""
    buf = b""
    while len(buf) < n:
        chunk = _sock_recv(sock, n - len(buf))
        if not chunk:
            raise OSError("Połączenie zamknięte podczas odczytu")
        buf += chunk
    return buf


# ================================================================
#  Warstwa 2: Ramki WebSocket (RFC 6455)
# ================================================================

def _ws_handshake(sock, host, port, path):
    """Wykonuje HTTP Upgrade do protokołu WebSocket.

    Wysyła żądanie GET z nagłówkami Upgrade, a następnie czyta odpowiedź
    bajt po bajcie, aby nie wciągnąć danych binarnych MQTT
    znajdujących się bezpośrednio za końcem nagłówków HTTP (\\r\\n\\r\\n).

    Rzuca OSError jeśli serwer nie zwróci kodu 101 Switching Protocols.
    """
    key = ubinascii.b2a_base64(uos.urandom(16)).strip().decode()
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Protocol: mqtt\r\n"
        f"Origin: http://{host}\r\n"
        f"User-Agent: MicroPython/PicoW\r\n"
        f"\r\n"
    )
    _sock_send(sock, request.encode())

    # Odczyt odpowiedzi HTTP bajt po bajcie
    resp = b""
    while b"\r\n\r\n" not in resp:
        b = _sock_recv(sock, 1)
        if not b:
            raise OSError("WebSocket handshake: połączenie zamknięte")
        resp += b

    if b"101" not in resp:
        raise OSError(f"WebSocket handshake nieudany: {resp[:128]}")


def _ws_send_frame(sock, data):
    """Wysyła dane jako zamaskowaną ramkę binarną WebSocket.

    Zgodnie z RFC 6455, klient MUSI maskować każdą ramkę wysyłaną
    do serwera. Używamy losowej 4-bajtowej maski XOR.

    Args:
        sock: Socket (zwykły lub SSL).
        data: Bajty do wysłania (pakiet MQTT).
    """
    mask = uos.urandom(4)
    payload_len = len(data)

    # Bajt 1: FIN=1 (0x80) + opcode=0x02 (binary) = 0x82
    header = bytearray([0x82])

    # Bajt 2+: długość payloadu z bitem maski (0x80)
    if payload_len < 126:
        header.append(0x80 | payload_len)
    elif payload_len < 65536:
        header.append(0x80 | 126)
        header += struct.pack(">H", payload_len)
    else:
        header.append(0x80 | 127)
        header += struct.pack(">Q", payload_len)

    header += mask

    # Maskowanie payloadu
    masked = bytearray(payload_len)
    for i, b in enumerate(data):
        masked[i] = b ^ mask[i % 4]

    _sock_send(sock, bytes(header) + bytes(masked))


def _ws_recv_frame(sock):
    """Odbiera jedną ramkę WebSocket.

    Automatycznie obsługuje ramki kontrolne:
    - opcode 0x08 (Close) → zwraca (None, None)
    - opcode 0x09 (Ping)  → odpowiada Pongiem, zwraca (None, None)

    Returns:
        (opcode, payload) lub (None, None) przy braku danych / zamknięciu.
    """
    try:
        header = _recv_exact(sock, 2)
    except OSError:
        return None, None

    if header is None:
        return None, None

    opcode = header[0] & 0x0F
    masked = (header[1] & 0x80) != 0
    length = header[1] & 0x7F

    # Rozszerzona długość (2 lub 8 bajtów)
    if length == 126:
        ext = _recv_exact(sock, 2)
        length = struct.unpack(">H", ext)[0]
    elif length == 127:
        ext = _recv_exact(sock, 8)
        length = struct.unpack(">Q", ext)[0]

    # Maska serwera (serwer NIE powinien maskować, ale obsługujemy na wszelki wypadek)
    if masked:
        mask = _recv_exact(sock, 4)

    payload = _recv_exact(sock, length) if length > 0 else b""

    if masked and payload:
        payload = bytearray(payload)
        for i in range(len(payload)):
            payload[i] ^= mask[i % 4]
        payload = bytes(payload)

    # Ramki kontrolne
    if opcode == 0x08:  # Connection Close
        return None, None
    if opcode == 0x09:  # Ping → odpowiadamy Pongiem
        _ws_send_frame(sock, b"")
        return None, None

    return opcode, payload


# ================================================================
#  Warstwa 3: Pakiety MQTT 3.1.1
# ================================================================

def _encode_remaining(length):
    """Koduje pole 'Remaining Length' pakietu MQTT (zmienna długość 1-4 bajtów)."""
    result = bytearray()
    while True:
        byte = length & 0x7F
        length >>= 7
        if length > 0:
            byte |= 0x80
        result.append(byte)
        if length == 0:
            break
    return bytes(result)


def _encode_str(s):
    """Koduje string MQTT (2 bajty długości + dane UTF-8)."""
    encoded = s.encode("utf-8")
    return struct.pack(">H", len(encoded)) + encoded


def _build_connect_pkt(client_id, user, password, keepalive):
    """Buduje pakiet MQTT CONNECT (typ 0x10).

    Flagi: Clean Session zawsze włączony.
    Uwierzytelnianie: user/password ustawiane warunkowo.
    """
    protocol_name = _encode_str("MQTT")
    protocol_level = bytes([4])  # MQTT 3.1.1

    connect_flags = 0x02  # Clean Session
    if user:
        connect_flags |= 0x80  # Username Flag
    if password:
        connect_flags |= 0x40  # Password Flag

    payload = _encode_str(client_id)
    if user:
        payload += _encode_str(user)
    if password:
        payload += _encode_str(password)

    variable_header = (
        protocol_name
        + protocol_level
        + bytes([connect_flags])
        + struct.pack(">H", keepalive)
    )

    body = variable_header + payload
    return bytes([0x10]) + _encode_remaining(len(body)) + body


def _build_subscribe_pkt(packet_id, topic):
    """Buduje pakiet MQTT SUBSCRIBE (typ 0x82, QoS 0)."""
    topic_filter = _encode_str(topic)
    variable_header = struct.pack(">H", packet_id)
    payload = topic_filter + bytes([0])  # QoS 0
    body = variable_header + payload
    return bytes([0x82]) + _encode_remaining(len(body)) + body


def _build_publish_pkt(topic, message):
    """Buduje pakiet MQTT PUBLISH (typ 0x30, QoS 0, bez retain)."""
    if isinstance(message, str):
        message = message.encode("utf-8")
    body = _encode_str(topic) + message
    return bytes([0x30]) + _encode_remaining(len(body)) + body


def _build_pingreq_pkt():
    """Buduje pakiet MQTT PINGREQ (typ 0xC0)."""
    return bytes([0xC0, 0x00])


def _parse_publish_payload(data):
    """Parsuje variable header odebranego PUBLISH.

    Returns:
        (topic_str, payload_bytes)
    """
    topic_len = struct.unpack(">H", data[:2])[0]
    topic = data[2:2 + topic_len].decode("utf-8")
    payload = data[2 + topic_len:]
    return topic, payload


# ================================================================
#  Klasa główna: MQTToverWS
# ================================================================

class MQTToverWS:
    """Klient MQTT 3.1.1 tunelowany przez WebSocket.

    Przeznaczony do pracy w pętli uasyncio:
    - connect()    – synchroniczne nawiązanie połączenia (~1-2s)
    - check_msg()  – nieblokujące sprawdzenie wiadomości (timeout=0)
    - publish()    – synchroniczna publikacja (szybka, nie blokuje zauważalnie)
    - subscribe()  – synchroniczna subskrypcja tematu
    - disconnect() – zamknięcie połączenia

    Odebrane wiadomości PUBLISH są przekazywane do callbacka
    ustawionego przez set_callback(fn), gdzie fn(topic_str, payload_bytes).

    Keepalive: automatycznie wysyła PINGREQ co połowę okresu keepalive
    podczas wywołań check_msg().
    """

    def __init__(self, host, port, path, client_id,
                 user=None, password=None, keepalive=60):
        """Inicjalizacja klienta (bez nawiązywania połączenia).

        Args:
            host:       Adres brokera (np. "mqtt.krlade.dev").
            port:       Port brokera (443 włącza automatycznie SSL/TLS).
            path:       Ścieżka WebSocket (zazwyczaj "/").
            client_id:  Unikalny identyfikator klienta MQTT.
            user:       Nazwa użytkownika MQTT (opcjonalne).
            password:   Hasło MQTT (opcjonalne).
            keepalive:  Okres keepalive w sekundach (domyślnie 60).
        """
        self._host = host
        self._port = port
        self._path = path
        self._client_id = client_id
        self._user = user
        self._password = password
        self._keepalive = keepalive
        self._sock = None
        self._base_sock = None
        self._packet_id = 1
        self._callback = None
        self._last_ping = time.time()

    def set_callback(self, fn):
        """Ustawia callback wywoływany przy odebraniu wiadomości PUBLISH.

        Args:
            fn: Funkcja o sygnaturze fn(topic_str, payload_bytes).
                Wywoływana synchronicznie z check_msg().
        """
        self._callback = fn

    def connect(self):
        """Nawiązuje połączenie TCP → TLS → WebSocket → MQTT.

        Sekwencja:
        1. Otwiera socket TCP do brokera.
        2. Jeśli port == 443, opakowuje w SSL/TLS (bez weryfikacji CA).
        3. Wykonuje handshake WebSocket (HTTP Upgrade).
        4. Wysyła pakiet MQTT CONNECT.
        5. Czeka na CONNACK (timeout 10s).
        6. Ustawia socket w tryb nieblokujący (timeout=0).

        Rzuca OSError przy niepowodzeniu na dowolnym etapie.
        """
        try:
            base_sock = socket.socket()
            addr = socket.getaddrinfo(self._host, self._port)[0][-1]
            base_sock.connect(addr)
            print(f"[MQTT] TCP połączono z {self._host}:{self._port}")

            # SSL/TLS dla portu 443 (Cloudflare wymaga TLS)
            if self._port == 443:
                sock = ssl.wrap_socket(
                    base_sock,
                    server_hostname=self._host,
                    cert_reqs=ssl.CERT_NONE  # Pico W nie ma trust store
                )
                print("[MQTT] SSL/TLS ustanowione")
            else:
                sock = base_sock

            self._sock = sock
            self._base_sock = base_sock

            # WebSocket handshake (HTTP 101 Switching Protocols)
            _ws_handshake(self._sock, self._host, self._port, self._path)
            print("[MQTT] WebSocket handshake OK")

            # MQTT CONNECT
            pkt = _build_connect_pkt(
                self._client_id, self._user, self._password, self._keepalive
            )
            _ws_send_frame(self._sock, pkt)

            # Oczekiwanie na CONNACK (timeout 10s)
            _sock_settimeout(self._base_sock, 10)

            start = time.time()
            data = None
            while time.time() - start < 10:
                opcode, data = _ws_recv_frame(self._sock)
                if data:
                    break
                time.sleep_ms(100)

            if data is None:
                raise OSError("Timeout: brak CONNACK od brokera")

            if len(data) < 4 or data[0] != 0x20:
                raise OSError(f"Nieoczekiwany pakiet zamiast CONNACK: "
                              f"{ubinascii.hexlify(data)}")

            rc = data[3]
            if rc != 0:
                raise OSError(f"MQTT CONNACK odmowa, kod: {rc}")

            # Tryb nieblokujący dla pętli głównej
            _sock_settimeout(self._base_sock, 0)
            self._last_ping = time.time()
            print(f"[MQTT] Połączono jako '{self._client_id}'")

        except Exception as e:
            self._cleanup()
            raise

    def subscribe(self, topic):
        """Subskrybuje temat MQTT (QoS 0).

        Args:
            topic: Temat do subskrypcji (np. "/device/PICO/commands").
        """
        pkt = _build_subscribe_pkt(self._packet_id, topic)
        self._packet_id = (self._packet_id + 1) & 0xFFFF
        _ws_send_frame(self._sock, pkt)
        print(f"[MQTT] Subskrypcja: {topic}")

    def publish(self, topic, message):
        """Publikuje wiadomość MQTT (QoS 0, bez retain).

        Args:
            topic:   Temat MQTT (np. "/device/PICO/data").
            message: Treść wiadomości (str lub bytes).
        """
        pkt = _build_publish_pkt(topic, message)
        _ws_send_frame(self._sock, pkt)

    def check_msg(self):
        """Sprawdza bufor socketu w trybie nieblokującym.

        Jeśli nadeszła wiadomość PUBLISH, wywołuje callback.
        Automatycznie wysyła PINGREQ co połowę okresu keepalive,
        aby broker nie zamknął połączenia.

        Bezpieczne do wywoływania w pętli co ~50ms z korutyny uasyncio.
        Nie blokuje, gdy brak danych (socket timeout=0).
        """
        # Automatyczny keepalive
        if time.time() - self._last_ping > self._keepalive // 2:
            _ws_send_frame(self._sock, _build_pingreq_pkt())
            self._last_ping = time.time()

        try:
            opcode, data = _ws_recv_frame(self._sock)
        except OSError:
            return  # Brak danych w buforze – normalne dla timeout=0

        if data is None:
            return

        ptype = data[0] & 0xF0

        if ptype == 0x30:  # PUBLISH
            # Dekodowanie pola Remaining Length (1-4 bajtów)
            idx = 1
            multiplier = 1
            remaining = 0
            while True:
                b = data[idx]
                idx += 1
                remaining += (b & 0x7F) * multiplier
                multiplier *= 128
                if not (b & 0x80):
                    break

            topic, payload = _parse_publish_payload(data[idx:])
            if self._callback:
                self._callback(topic, payload)

        # PINGRESP (0xD0), SUBACK (0x90) i inne – ignorujemy (poprawne zachowanie)

    def disconnect(self):
        """Wysyła pakiet MQTT DISCONNECT i zamyka połączenie."""
        if self._sock:
            try:
                _ws_send_frame(self._sock, bytes([0xE0, 0x00]))
                print("[MQTT] Rozłączono")
            except Exception:
                pass
            self._cleanup()

    def _cleanup(self):
        """Zamyka socket i czyści stan wewnętrzny."""
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
            self._base_sock = None
