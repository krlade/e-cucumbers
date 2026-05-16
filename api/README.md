# E-Cucumbers Webapp

Dokumentacja techniczna dla centralnej części serwerowej (Webapp) projektu **E-Cucumbers**. Projekt ma na celu udostępnienie interfejsu webowego (HMI) oraz bezpiecznego API dla Jednostki Centralnej (Raspberry Pi), która kontroluje i agreguje dane z urządzeń końcowych (węzłów bazujących na RPi Pico / ESP32) w inteligentnym systemie hodowli ogórków.

---

## Spis treści
1. [Wymagania i instalacja](#wymagania-i-instalacja)
2. [Architektura rozwiązań](#architektura-rozwiazan)
3. [Widoki i funkcjonalności webowe](#widoki-i-funkcjonalnosci-webowe)
4. [Dokumentacja API (Endpointy)](#dokumentacja-api-endpointy)
5. [Rozwój w przyszłości](#rozwoj-w-przyszlosci)

---

## 1. Wymagania i instalacja

Projekt opiera się bazowo na frameworku **Django** i paczce **Django REST Framework (DRF)**. Jako bazę danych wykorzystuje system `SQLite` we wczesnej fazie projektu dla zachowania najwyższej prostoty – jedno z głównych rygorystycznych założeń deweloperskich to absolutne unikanie overengineeringu.

### Wymagania środowiskowe
- Python 3.10+
- Menedżer pakietów `pip` oraz `virtualenv`

### Setup projektu (Krok po kroku)

Dzięki przygotowanym narzędziom konfiguracyjnym, instalacja repozytorium na nowej maszynie jest całkowicie zautomatyzowana (zarówno dla systemu Windows, jak i środowisk Linux/macOS).

1. **Uruchomienie automatycznego skryptu (Windows / Linux):**
   W katalogu `api/` zlokalizuj skrypt konfiguracyjny odpowiedni dla Twojego środowiska i go uruchom.

   **Na systemie Windows:**
   ```bash
   setup.bat
   ```
   **Na systemie Linux / macOS:**
   ```bash
   bash setup.sh
   ```
   *Skrypt samodzielnie zajmie się:*
   * Stworzeniem izolowanego środowiska wirtualnego (`.venv`)
   * Pobraniem wszystkich pakietów z `requirements.txt` (Django, DRF, JWT, drf-spectacular, CORS)
   * Zastosowaniem wszystkich migracji bazodanowych
   * Powołaniem głównego konta administratora `admin` / `admin123`

2. **Uruchomienie serwera deweloperskiego:**
   ```bash
   .venv\Scripts\activate      # Windows
   source .venv/bin/activate   # Linux / macOS
   python manage.py runserver
   ```
   Serwer dostępny pod: `http://127.0.0.1:8000`

3. **Interaktywna dokumentacja API (Swagger):**

   Po uruchomieniu serwera dostępne są:

   | URL | Opis |
   |---|---|
   | `http://127.0.0.1:8000/api/docs/` | Swagger UI — testowanie endpointów w przeglądarce |
   | `http://127.0.0.1:8000/api/redoc/` | ReDoc — czytelna dokumentacja |
   | `http://127.0.0.1:8000/api/schema/` | Surowy plik OpenAPI 3.0 (YAML) |

---

## 2. Architektura rozwiązań

Aplikacja jest minimalnym rozwiązaniem typu monolith — łączy widoki HTML (szablony Django) z interfejsami JSON API, z wyraźnym podziałem odpowiedzialności.

* **`ecucumbers/`** — Główny moduł aplikacyjny: ustawienia silnika DRF, konfiguracja JWT, routing główny, CORS, Swagger (drf-spectacular).
* **`accounts/`** — Moduł operacji na profilach: rejestracja kont, logowanie, generowanie tokenów JWT, zarządzanie rolami użytkowników (panel admina).
* **`nodes/`** — Sub-aplikacja obsługująca cały cykl życia urządzeń IoT:
  * `CentralUnit` — zarejestrowane gateway'e (Raspberry Pi)
  * `DeviceOwnership` — relacja właściciel/współdzielenie z rolami `admin` / `viewer`
  * `ControllableNode` — węzeł końcowy (Pico): maksymalnie **1 czujnik** (`sensor_type`) i opcjonalnie 1 urządzenie sterowane (`gpio` + `peripheral_type`)
  * `QueuedCommand` — kolejka komend od użytkownika, odbierana przez gateway przy heartbeat
  * `TelemetryReading` — append-only logi z czujników; `sensor_type` pochodzi z rejestracji węzła
* **`tests/`** — Testy integracyjne weryfikujące poprawność endpointów.

Do autoryzacji w REST API używany jest **JWT (JSON Web Tokens)** z parą kluczy `access` / `refresh`. Zarówno użytkownicy ludzcy, jak i urządzenia (gateway) używają JWT — urządzenia mają własne konta systemowe (`device_user`).

### Zasada: jeden czujnik na węzeł

Każdy fizyczny węzeł (`node_id`) podłączony do gateway'a może mieć **dokładnie jeden typ czujnika**. Typ czujnika jest deklarowany raz podczas rejestracji węzła (`/register-peripherals/`) i nie jest powtarzany przy każdym odczycie telemetrii. Dzięki temu payload telemetrii jest minimalny: `{"node_id": "Pico_01", "value": 23.5}`.

---

## 3. Widoki i funkcjonalności webowe

* **`base.html`** — Szkielet strony z nawigacją i globalnym CSS (zielony motyw).
* **`dashboard.html`** — Panel użytkownika: dane konta, generowanie Tokenu Parowania z odliczaniem (15 min), lista zarejestrowanych Jednostek Centralnych z liczbą lamp i zraszaczy, przycisk panelu admina (tylko dla superuser).
* **`manage_users.html`** — Panel admina: masowe zarządzanie rolami użytkowników (`superuser` / `staff` / `user`), blokada modyfikacji konta `admin`.

---

## 4. Dokumentacja API (Endpointy)

> Wszystkie endpointy API można testować interaktywnie przez Swagger UI: `http://127.0.0.1:8000/api/docs/`

### `MODUŁ: API / ACCOUNTS /`

| Metoda | Endpoint | Autoryzacja | Opis | Payload (JSON) | Odpowiedź |
|---|---|---|---|---|---|
| `POST` | `/api/accounts/register/` | ❌ Brak | Rejestracja nowego konta użytkownika | `{"username":"x", "email":"x@x.com", "password":"x"}` | `201` — dane konta + tokeny JWT |
| `POST` | `/api/accounts/login/` | ❌ Brak | Logowanie, wystawia tokeny JWT | `{"username":"x", "password":"x"}` | `200` — `{"refresh":"...", "access":"..."}` |
| `POST` | `/api/accounts/token/refresh/` | ❌ Brak | Odświeża wygasły token `access` | `{"refresh":"<token>"}` | `200` — nowy `access` |
| `GET` | `/api/accounts/me/` | ✅ Bearer JWT (user) | Profil aktualnie zalogowanego użytkownika | — | `200` — dane użytkownika |

### `MODUŁ: API / NODES /`

| Metoda | Endpoint | Autoryzacja | Opis | Payload (JSON) | Odpowiedź |
|---|---|---|---|---|---|
| `POST` | `/api/nodes/pairing-token/` | ✅ Bearer JWT (user) | Generuje Token Parowania ważny 15 min (`TEMP-XXXX`) | — | `201` — `{"token":"TEMP-8492", "expires_at":"...", "expires_in_seconds":900}` |
| `POST` | `/api/nodes/register-device/` | ❌ Brak | Rejestruje gateway lub ponownie go rejestruje po factory reset. Tworzy konto systemowe urządzenia i nadaje właścicielowi rolę admin. | `{"device_id":"2137", "pairing_token":"TEMP-8492"}` | `200` — `{"device_id":"2137", "owner":"Jan", "access":"...", "refresh":"..."}` |
| `POST` | `/api/nodes/register-peripherals/` | ✅ Bearer JWT (device) | Gateway rejestruje węzły końcowe (idempotentne — upsert). Każdy węzeł może mieć czujnik (`sensor_type`) i/lub urządzenie sterowane (`gpio` + `peripheral_type`). | `{"device_id":"2137", "peripherals":[{"node_id":"Pico_01", "gpio":1, "peripheral_type":"LAMP", "sensor_type":"temperature"}]}` | `200` — lista zarejestrowanych węzłów |
| `GET` | `/api/nodes/peripherals/?device_id=2137` | ✅ Bearer JWT (user) | Lista węzłów gateway'a. Użytkownik musi mieć dowolną rolę w `DeviceOwnership`. | — | `200` — węzły z `allowed_commands` per typ |
| `POST` | `/api/nodes/command/` | ✅ Bearer JWT (user) | Kolejkuje komendę do węzła końcowego (status `pending`). Czas podawany w minutach. | `{"device_id":"2137", "node_id":"Pico_01", "gpio":1, "command":["TURN_ON_FOR", 480]}` | `201` — zakolejkowana komenda |
| `POST` | `/api/nodes/heartbeat/` | ✅ Bearer JWT (device) | Gateway odbiera wszystkie komendy `pending` i oznacza je jako `delivered`. Tożsamość gateway'a wynika z JWT. | — | `200` — `{"device_id":"2137", "pending_count":5, "commands":[...]}` |
| `POST` | `/api/nodes/telemetry/` | ✅ Bearer JWT (device) | Gateway przesyła odczyt z czujnika węzła. `sensor_type` jest pobierany automatycznie z rejestracji węzła — nie trzeba go podawać. | `{"node_id":"Pico_01", "value":23.5}` | `201` — zapisany odczyt z `sensor_type` |

#### Typy urządzeń i ich komendy

| `peripheral_type` | Dostępne komendy | Parametr |
|---|---|---|
| `LAMP` | `TURN_ON`, `TURN_OFF` | — |
| `LAMP` | `TURN_ON_FOR` | `time` (minuty, wymagany) |
| `SPRINKLER` | `WATER_PUMP_ON` | `time` (minuty, wymagany) |

#### Typy czujników (`sensor_type`)

| Wartość | Opis |
|---|---|
| `temperature` | Temperatura (°C) |
| `humidity` | Wilgotność (%) |
| `light` | Natężenie światła (lux) |

---

## 5. Schemat bazy danych

![Schemat bazy danych](db-schema-visualization.png)

---

## 6. Rozwój w przyszłości

1. **Faza 2 — Telemetria i sterowanie:** ✅ Zrealizowane — endpointy `telemetry/`, `command/`, `heartbeat/` są gotowe. Pozostaje: wykresy telemetrii na dashboardzie oraz panel sterowania wysyłający komendy bezpośrednio z UI.
2. **Faza 3 — Współdzielenie uprawnień:** Generowanie kodów zaproszeniowych (`share-code/`), dołączanie do istniejącej Jednostki Centralnej (`claim-shared/`), zarządzanie rolami per urządzenie.
3. **Dashboard — aktywne widgety:** Podmiana placeholderów na listę lamp i zraszaczy z przyciskami sterowania oraz wykresy telemetrii w czasie rzeczywistym.
4. **Alerty Discord (Opcjonalnie):** Wysyłanie powiadomień o anomaliach przez WebHook na czat Discord.
