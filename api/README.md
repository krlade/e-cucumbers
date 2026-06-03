# E-Cucumbers Webapp

Dokumentacja techniczna serwerowej części projektu **E-Cucumbers** — systemu monitorowania i sterowania uprawą ogórków. Webapp stanowi centrum systemu: udostępnia Dashboard dla użytkownika oraz API dla Gateway (Raspberry Pi) i węzłów końcowych (RPi Pico).

---

## Spis treści
1. [Wymagania i instalacja](#1-wymagania-i-instalacja)
2. [Architektura](#2-architektura)
3. [Dashboard](#3-dashboard)
4. [API](#4-api)
5. [Symulator](#5-symulator)
6. [Wymagania implementacyjne dla Gateway](#6-wymagania-implementacyjne-dla-gateway)
7. [Schemat bazy danych](#7-schemat-bazy-danych)

---

## 1. Wymagania i instalacja

Projekt oparty na **Django** + **Django REST Framework**. Baza danych: SQLite.

### Wymagania
- Python 3.10+

### Setup

**Windows:**
```bash
setup.bat
```
**Linux / macOS:**
```bash
bash setup.sh
```

Skrypt tworzy `.venv`, instaluje zależności z `requirements.txt`, stosuje migracje i tworzy konto `admin` / `admin123`.

### Uruchomienie

```bash
.venv\Scripts\activate      # Windows
source .venv/bin/activate   # Linux / macOS
python manage.py runserver
```

Serwer dostępny pod `http://127.0.0.1:8000`. Swagger UI: `http://127.0.0.1:8000/api/docs/`

---

## 2. Architektura

Minimalny monolit Django: widoki HTML (szablony) + JSON API.

**Modele (`nodes/`):**
- `PairingToken` — token parowania `TEMP-XXXX`, ważny 15 min
- `CentralUnit` — zarejestrowany Gateway z JWT (`device_user`) i polem `last_heartbeat`
- `DeviceOwnership` — relacja użytkownik ↔ gateway, role: `admin` / `viewer`
- `ControllableNode` — opcjonalna konfiguracja węzła nadana przez użytkownika (etykieta, `sensor_type`, `gpio`)
- `QueuedCommand` — kolejka komend powiązana z `CentralUnit` + `node_id` + `gpio`; statusy: `pending` / `delivered`
- `TelemetryReading` — surowe dane z węzłów; `raw_payload` = oryginalny JSON od Pico

**Zasada relay:** Gateway jest czystym przekaźnikiem. Przesyła surowe dane od węzłów Pico bez żadnej interpretacji. Odbiera komendy `TURN_ON` / `TURN_OFF` i wykonuje je fizycznie na GPIO. Całą logikę (timery, interpretacja danych, konfiguracja) realizuje Webapp.

---

## 3. Dashboard

URL: `/` (wymaga logowania)

Dla każdej zarejestrowanej Jednostki Centralnej Dashboard wyświetla:

- Badge **Online / Offline** z czasem ostatniego heartbeatu
- **Wykresy telemetrii** (Chart.js, polling co 4s) z wyborem zakresu: 5 min / 15 min / 30 min / wszystko
- **Karty „Nowy węzeł"** — gdy Pico zaczyna nadawać bez konfiguracji, pojawia się formularz do nadania etykiety i przypisania typu czujnika
- **Panel sterowania GPIO** — Włącz / Wyłącz / Włącz na czas / Nawadniaj
- **Dziennik komend** z czytelnymi opisami (np. „Włączono na 8 min")
- **Alert ponownego parowania** gdy gateway jest Offline — generowanie nowego tokenu jednym przyciskiem

Inne widoki:

| URL | Opis |
|---|---|
| `/simulation/` | Symulator gateway'a (tylko superuser) |
| `/accounts/register/` | Rejestracja |
| `/accounts/login/` | Logowanie |
| `/accounts/manage-users/` | Zarządzanie rolami (tylko superuser) |

---

## 4. API

> Swagger UI: `http://127.0.0.1:8000/api/docs/`

### Accounts

| Metoda | Endpoint | Auth | Opis |
|---|---|---|---|
| `POST` | `/api/accounts/register/` | ❌ | Rejestracja. Payload: `{username, email, password}`. Zwraca `{user, access, refresh}` |
| `POST` | `/api/accounts/login/` | ❌ | Logowanie. Zwraca `{access, refresh}` |
| `POST` | `/api/accounts/token/refresh/` | ❌ | Odświeża token. Payload: `{refresh}`. Zwraca `{access}` |
| `GET` | `/api/accounts/me/` | ✅ user | Profil zalogowanego użytkownika |

### Nodes

| Metoda | Endpoint | Auth | Opis |
|---|---|---|---|
| `POST` | `/api/nodes/pairing-token/` | ✅ user | Generuje token `TEMP-XXXX` ważny 15 min. Zwraca `{token, expires_at, expires_in_seconds}` |
| `POST` | `/api/nodes/register-device/` | ❌ | Paruje gateway. Payload: `{device_id, pairing_token}`. Zwraca `{device_id, access, refresh}` |
| `DELETE` | `/api/nodes/register-device/` | ✅ user | Wyrejestrowuje gateway. Payload: `{device_id}` |
| `POST` | `/api/nodes/heartbeat/` | ✅ device | Brak payloadu. Aktualizuje `last_heartbeat`, zwraca i oznacza komendy `pending→delivered`. Zwraca `{device_id, pending_count, commands}` |
| `POST` | `/api/nodes/telemetry/` | ✅ device | Surowy odczyt. Payload: `{node_id, payload: {data: 23.5}}`. Zwraca `{id, node_id, sensor_type, value, raw_payload, recorded_at}` |
| `GET` | `/api/nodes/telemetry/?device_id=` | ✅ user/device | Historia odczytów. Filtry: `node_id`, `sensor_type`, `limit`. Wyniki ASC po `recorded_at` |
| `POST` | `/api/nodes/command/` | ✅ user | Kolejkuje komendę. Payload: `{device_id, node_id, gpio, command: ["TURN_ON_FOR", 60]}`. Zwraca `{..., human_description}` |
| `GET` | `/api/nodes/command/?device_id=` | ✅ user/device | Historia komend. Filtr: `limit` (domyślnie 20) |
| `POST` | `/api/nodes/node-config/` | ✅ user | Konfiguruje węzeł z Dashboardu. Payload: `{device_id, node_id, sensor_type, label}` |
| `GET` | `/api/nodes/peripherals/?device_id=` | ✅ user/device | Lista węzłów z konfiguracją (używane przez panel sterowania) |
| `GET` | `/api/nodes/user-devices/` | ✅ user | Wszystkie gateway'e użytkownika z rolą i statusem online |

#### Walidacja komend

Serwer zwraca `400` jeśli:
- `device_id` nie istnieje lub brak dostępu
- `gpio` poza zakresem 0–40
- `command[0]` spoza zbioru: `TURN_ON`, `TURN_OFF`, `TURN_ON_FOR`, `WATER_PUMP_ON`
- `TURN_ON_FOR` / `WATER_PUMP_ON` — brak parametru czasu (`command[1]`)
- `TURN_ON` / `TURN_OFF` — podano niepotrzebny parametr czasu

#### Dostępne komendy

| Komenda | Parametr | Opis |
|---|---|---|
| `TURN_ON` | — | GPIO wysoki (natychmiastowe) |
| `TURN_OFF` | — | GPIO niski (natychmiastowe) |
| `TURN_ON_FOR` | czas (min) | Włącz; Webapp automatycznie kolejkuje `TURN_OFF` po upływie czasu |
| `WATER_PUMP_ON` | czas (min) | Nawadnianie; Webapp automatycznie kolejkuje `TURN_OFF` po upływie czasu |

#### Przykłady JSON

**Odczyt telemetrii:**
```json
{ "id": 101, "node_id": "Pico_01", "sensor_type": "temperature",
  "value": 23.5, "raw_payload": {"data": 23.5}, "recorded_at": "2026-06-03T10:05:00Z" }
```

**Komenda (historia):**
```json
{ "id": 42, "node_id": "Pico_01", "gpio": 1, "command": "TURN_ON_FOR",
  "time": 60, "human_description": "Włączono na 60 min", "status": "delivered" }
```

**Heartbeat — komenda dla gateway'a:**
```json
{ "id": 42, "node_id": "Pico_01", "gpio": 1, "command": "TURN_ON" }
```

---

## 5. Symulator

URL: `/simulation/` — tylko dla kont `superuser`.

Emuluje firmware gateway'a w przeglądarce. Umożliwia pełne przetestowanie protokołu gateway ↔ API bez fizycznego sprzętu.

| Funkcja | Opis |
|---|---|
| **Parowanie** | Formularz `device_id` + token `TEMP-XXXX`. JWT zapisywane w `localStorage`. |
| **Węzły** | Dodawanie/usuwanie węzłów. Auto-synchronizacja z `POST /api/nodes/register-peripherals/`. |
| **Heartbeat** | Start/Stop, konfigurowalna częstotliwość (2–60s). Komendy wykonywane natychmiast na wskaźnikach LED. |
| **Telemetria** | Suwak + tryb (manualny / szum losowy / sinusoida). Wysyła `POST /api/nodes/telemetry/` co 5s. |
| **Stan GPIO** | LED z odliczaniem dla komend czasowych. Odtwarzanie stanu po odświeżeniu przez `GET /api/nodes/command/`. |
| **Konsola** | 🔵 System / 🟢 OK / 🔴 Błąd / 🩵 Telemetria / 🟠 Komendy. Wyczyść / Kopiuj. |
| **JWT refresh** | Automatyczne odświeżanie przy `401`. Błąd refresh → factory reset. |

---

## 6. Wymagania implementacyjne dla Gateway

Gateway pełni rolę **czystego przekaźnika**. Nie implementuje logiki, timerów ani abstrakcji.

### 6.1 Stan lokalny

Plik `station.json`:
```json
{
  "device_id": "RPi_01",
  "access_token": "<jwt>",
  "refresh_token": "<jwt>" 
}
```

### 6.2 Parowanie

Użytkownik generuje token na Dashboardzie (`TEMP-XXXX`, 15 min).

```http
POST /api/nodes/register-device/
Content-Type: application/json

{ "device_id": "RPi_01", "pairing_token": "TEMP-1234" }
```

Odpowiedź: `{ "device_id": "RPi_01", "access": "...", "refresh": "..." }`

Ponowne parowanie z tym samym `device_id` wydaje nowe tokeny — historia danych zostaje.

### 6.3 Heartbeat (co 5–30s)

```http
POST /api/nodes/heartbeat/
Authorization: Bearer <access_token>
```

Odpowiedź:
```json
{
  "device_id": "RPi_01", "pending_count": 2,
  "commands": [
    { "id": 42, "node_id": "Pico_01", "gpio": 1, "command": "TURN_ON" },
    { "id": 43, "node_id": "Pico_02", "gpio": 2, "command": "TURN_OFF" }
  ]
}
```

Gateway iteruje `commands` i dla każdej komendy ustawia pin `gpio` węzła `node_id` w stan wysoki (`TURN_ON`) lub niski (`TURN_OFF`). Komendy czasowe Gateway nigdy nie widzi — Webapp przekłada je na `TURN_ON` + późniejszy `TURN_OFF`. Potwierdzenie dostarczenia jest automatyczne — gateway nic nie odsyła.

### 6.4 Telemetria

Pico wysyła `{"data": 23.5}`. Gateway przekazuje bez modyfikacji:

```http
POST /api/nodes/telemetry/
Authorization: Bearer <access_token>
Content-Type: application/json

{ "node_id": "Pico_01", "payload": {"data": 23.5} }
```

Węzeł nie musi być wcześniej zarejestrowany. Konfigurację (`sensor_type`, etykieta) nadaje użytkownik z Dashboardu po tym, jak dane zaczną napływać.

### 6.5 Odświeżanie JWT

Przy `401` gateway wykonuje:

```http
POST /api/accounts/token/refresh/
Content-Type: application/json

{ "refresh": "<refresh_token>" }
```

Zwraca `{ "access": "..." }`. Jeśli refresh też zwróci `401` → konieczne ponowne parowanie.

### 6.6 Pętla główna

```
[Start]
  ↓
Wczytaj station.json (device_id, access, refresh)
  ↓
Brak tokenów? → Czekaj na TEMP-XXXX → POST /register-device/
  ↓
[Pętla, tick co ~10s]
  ├── POST /heartbeat/     → wykonaj komendy (TURN_ON / TURN_OFF na GPIO)
  ├── POST /telemetry/ × N → dla każdego węzła Pico z nowym odczytem
  └── Przy 401 → POST /token/refresh/ → przy błędzie → wróć do parowania
```

### 6.7 Kody HTTP

| Kod | Akcja |
|---|---|
| `200 / 201` | OK |
| `400` | Błąd danych — zaloguj, nie powtarzaj |
| `401` | Wygasły token → odśwież |
| `403` | Brak uprawnień → restart parowania |

---

## 7. Schemat bazy danych

![Schemat bazy danych](db-schema-visualization.png)
