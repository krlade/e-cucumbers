# E-Cucumbers Webapp

Dokumentacja techniczna dla centralnej części serwerowej (Webapp) projektu **E-Cucumbers**. Projekt ten ma na celu udostępnienie interfejsu webowego (HMI) oraz bezpiecznego API dla Jednostki Centralnej (Raspberry Pi), która kontroluje i agreguje dane z urządzeń końcowych (węzłów bazujących na RPi Pico / ESP32) w inteligentnym systemie hodowli ogórków.

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
   W leżącym w korzeniu projektu `d:\Code\Projects\api` oknie eksploratora plików zlokalizuj skrypt konfiguracyjny odpowiedni dla Twojego środowiska i go uruchom.
   
   **Na systemie Windows:**
   ```bash
   setup.bat
   ```
   **Na systemie Linux / macOS:**
   ```bash
   bash setup.sh
   ```
   *Skrypt w sposób łańcuchowy samodzielnie i bezpiecznie zajmie się:*
   * Stworzeniem izolowanego katalogu ze środowiskiem (tzw. `virtualenv`) do folderu `.venv`
   * Aktywacją stworzonego środowiska pod maską
   * Wczytaniem i pobraniem wszystkich pakietów wypisanych w `requirements.txt`
   * Wywołaniem sub-modułu z jądra bazy (automatyczne relacje i powołanie głównego administratora `admin` + `admin123`)

2. **Uruchomienie weryfikacyjnego serwera developerskiego Django:**
   Aby włączyć platformę po pomyślnej izolacji `setup.bat`, otwórz terminal w głównej ścieżce i uaktywnij środowisko przed komendą runserver:
   ```bash
   .venv\Scripts\activate
   python manage.py runserver
   ```
   *Teraz interfejs wizualny i interfejs API projektu są udostępniane pod adresem deweloperskim: `http://127.0.0.1:8000`*

---

## 2. Architektura rozwiązań

Aplikacja jest minimalnym rozwiązaniem typu monolith (łączy podział widoków na część webową wspartą o szablony i na interfejsy JSON API) z wyraźnym podziałem odpowiedzialności. 

* **`ecucumbers/`** - Główny moduł aplikacyjny z definicjami połączeń (zabezpieczenia, ustawienia silnika DRF, instalacja biblioteki JWT dla wtyczki REST, struktura główna routingu bazy). Wszystkie niezbędne porty CORS pozwalające na zrealizowane odpytywanie zewnętrzne na wariantach deweloperskich są zdefiniowane tutaj.
* **`accounts/`** - Moduł odpowiedzialny wyłącznie za operacje logiczne na profilach (rejestracje kont z mechanizmem walidacyjnym, zarządzanie logowaniem i generowanie docelowych poświadczeń szyfrowanych).
* **`nodes/`** - Sub-aplikacja obsługująca parowanie, rejestrację i sterowanie Jednostkami Centralnymi (Raspberry Pi). Zawiera modele: `CentralUnit`, `DeviceOwnership` (role admin/viewer), `ControllableNode` (peryferia końcowe z mapowaniem GPIO i legalnymi komendami per typ). Przygotowana na telemetrię i komendy sterujące (Faza 2).
* **`tests/`** - Folder z testami integracyjnymi weryfikującymi poprawność endpointów.

Do komunikacji w ramach protokołu REST API używany jest autoryzacyjny zbiór mechanizmów z wtyczką **JWT (JSON Web Tokens)** implementując zrzut kluczy `access` i `refresh`. 

---

## 3. Widoki i funkcjonalności webowe

Do obsługi wizualnego interfejsu (HMI sterującego) dla użytkownika przeglądarki wybrano szablony i mechanizmy HTML sprzęgnięte natywnie z widokami w Django, wykorzystujące dogodnie strukturę dziedziczenia.

* **Wygenerowane zasady widoków na bazie HTML:**
  * Szablon master: **`base.html`** – plik stanowiący ogólnozakrojony szkielet strony operujący globalną strukturą powtarzaną oraz dołączonym arkuszem stylizujących kompozycji CSS.
  * Szablon zalogowanego panelu: **`dashboard.html`** - Główny hub powitalny autoryzowanego zarządcy, ukazujący szczegóły podpiętego konta. Zawiera kartę **"Dodaj urządzenie"** umożliwiającą generowanie Tokenu Parowania z odliczaniem czasu ważności (15 min). Ujawnia przycisk panelu sterowania, jeśli obecny stan przypisania usera pozwala na bycie `superuser`.
  * Szablon adminujący personelem: **`manage_users.html`** - chroniony, zamknięty hub z kontrolką zbiorczej tabeli ról (tzw. masowy przydział uprawnień wielu pracownikom na raz). Posiada mechanizm blokujący odbezpieczenie lub degradację głównego administratora `admin`.
* **Sesje Webowe w Django:** Systemy obsługujące widoki przeglądarni korzystają z podzespołowego standardu uwierzytelniania wbudowanego w jądro Django. Użytkownik wizualny wykorzystuje tzw. logowanie z wykorzystaniem `LoginView` powiązanym z `sessions`. Wyciąganie tych poświadczeń (jak logowanie widokowe czy formularz rejestracji html) nie generuje zbędnych obciążeń bazy. W razie potyczek, sesja ratuje logikę nadpisywania uprawień.

---

## 4. Dokumentacja API (Endpointy)

Obecne zestawienie docelowych API (posiadają pełne funkcjonalności ułatwiające zestawianie uwierzeytelniań dla poszczególnych modułów systemu IoT do poświadczeń i dalszych kroków autoryzacyjnych):

### `MODUŁ: API / ACCOUNTS / ` 

| Typ w API | Ścieżka (Endpoint) | Autoryzacja | Opis wykonania | Wymagany ładunek wejściowy do zgłoszenia (Tylko JSON) | Typ Odpowiedzi (Standard. HTTP |
|---|---|---|---|---|---|
| `POST` | `/api/accounts/register/` | ❌ Brak | Zleca wniosek utworzenia subkonta | `{"username":"x", "email":"x@x.com", "password":"x"}` | Status `201`. Odsyła parametry konta i dwa Tokeny JWT. |
| `POST` | `/api/accounts/login/` | ❌ Brak | Autentykacja klienta, wystawia tokeny systemowe. | `{"username":"x", "password":"x"}` | Status `200`. Zawiera wygenerowane: `{"refresh":"<k>", "access":"<k>"}` |
| `POST` | `/api/accounts/token/refresh/` | ❌ Brak | Odświeża miniony klucz autoryzujący `access`. | `{"refresh":"<twój_działający_odnawiający_token>"}` | Status `200`. Zawiera tylko jeden certyfikat: nowy klucz `"access"`. |
| `GET` | `/api/accounts/me/` | ✅ Zabezp. Bearer token JWT | Endpoint weryfikacyjny. Testuje i wyrzuca parametry użytkownika, testuje token u centrali w RPi. | Odpytywanie bez JSON, wymóg wprowadzenia nagłówka API `Authorization: Bearer <t_access>`| Status `200`. Odpowiedź autentykacji po weryfikacji toku na profil. |


### `MODUŁ: API / NODES /` – Zaimplementowane

| Typ w API | Ścieżka (Endpoint) | Autoryzacja | Opis wykonania | Wymagany ładunek wejściowy (JSON) | Typ Odpowiedzi |
|---|---|---|---|---|---|
| `POST` | `/api/nodes/pairing-token/` | ✅ Bearer JWT (user) | Generuje tymczasowy Token Parowania (ważny 15 min, format `TEMP-XXXX`), powiązany z kontem użytkownika. | Brak ładunku (pusty POST) | Status `201`. `{"token":"TEMP-8492", "expires_at":"...", "expires_in_seconds": 900}` |
| `POST` | `/api/nodes/register-device/` | ❌ Brak | Rejestracja lub ponowna rejestracja Jednostki Centralnej po factory reset. Waliduje Token Parowania, tworzy rekord urządzenia, nadaje właścicielowi rolę admin, zwraca JWT dla urządzenia. | `{"device_id":"2137", "pairing_token":"TEMP-8492"}` | Status `200`. `{"device_id":"2137", "owner":"Jan", "access":"<k>", "refresh":"<k>"}` |
| `POST` | `/api/nodes/register-peripherals/` | ✅ Bearer JWT (device) | Gateway rejestruje swoje peryferia (lampy, zraszacze) z mapowaniem GPIO. Operacja idempotentna (upsert). JWT musi należeć do tego konkretnego gatewaya. | `{"device_id":"2137", "peripherals":[{"node_id":"Pico_01", "gpio":1, "peripheral_type":"LAMP"}]}` | Status `200`. Lista zarejestrowanych peryferiów z legalnymi komendami. |
| `GET` | `/api/nodes/peripherals/?device_id=2137` | ✅ Bearer JWT (user) | Pobiera listę peryferiów gatewaya. Użytkownik musi mieć dowolną rolę w `DeviceOwnership`. | Brak ładunku | Status `200`. Lista peryferiów z `allowed_commands` per typ. |
| `POST` | `/api/nodes/command/` | ✅ Bearer JWT (user) | Użytkownik wysyła komendę do konkretnego urządzenia końcowego. Waliduje legalność komendy dla danego `peripheral_type` oraz parametr czasu. Kolejkuje polecenie (status `pending`) do odebrania przez heartbeat. Czas zawsze podawany w minutach. | `{"device_id":"2137", "node_id":"Pico_01", "gpio":1, "command":["TURN_ON_FOR", 480]}` | Status `201`. Zakolejkowane polecenie z polem `status: pending`. |
| `POST` | `/api/nodes/heartbeat/` | ✅ Bearer JWT (device) | Gateway odbiera wszystkie zakolejkowane komendy (`pending`). Oznacza je jako `delivered`. Żadnego payloadu — tożsamość urządzenia wynika z JWT. | Brak payloadu | Status `200`. `{"device_id":"2137", "pending_count": 5, "commands": [...]}` |

### `MODUŁ: API / NODES /` – Planowane (Faza 2)

| Planowana Metoda | Oczekiwana docelowa struktura Endpointa | Rodzaj i Autoryzacja | Skonceptowany Wsad / Payload dla JSON |
|---|---|---|---|
| POST | `/api/nodes/telemetry/` | ✅ JWT urządzenia | `{"node_id": "Pico_01", "temp": 24.5, "humidity": 60, "light": 850}` |
| GET | `/api/nodes/status/` | ✅ JWT użytkownika | Brak ładunku POST |

---

## 5. Rozwój w przyszłości

1. **Faza 2 – Telemetria i sterowanie:** Endpointy `telemetry/`, `command/`, `heartbeat/` oraz modele pomiarów (temperatura, wilgotność, natężenie światła). Wykresy na dashboardzie. Panel sterowania wysyłający komendy do urządzeń końcowych (LAMP / SPRINKLER).
2. **Faza 3 – Współdzielenie uprawnień:** Generowanie kodów zaproszeniowych (`share-code/`), dołączanie do istniejącej Jednostki Centralnej (`claim-shared/`), zarządzanie rolami per urządzenie.
3. **Dashboard:** Podmiana placeholderów na aktywne widgety — listę lamp i zraszaczy z przyciskami sterowania, wykresy telemetrii.
4. **Alerty Discord (Opcjonalnie):** Wysyłanie powiadomień o anomaliach przez WebHook na czat Discord.
