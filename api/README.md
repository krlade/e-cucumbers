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
* **`nodes/`** - Zdefiniowana, sterylna sub-aplikacja ("wtyczka projektu"), do której spływać będą pomiary z czujników centrali środowiskowej i przez którą emitowane będą komendy sterujące na sprzęt (np. obsługa systemów wodnych). Obecnie "czeka" ze stworzonym oknem integracyjnym ze względu na oczekiwania narzuconej od góry struktury od fizycznych pomiarów.

Do komunikacji w ramach protokołu REST API używany jest autoryzacyjny zbiór mechanizmów z wtyczką **JWT (JSON Web Tokens)** implementując zrzut kluczy `access` i `refresh`. 

---

## 3. Widoki i funkcjonalności webowe

Do obsługi wizualnego interfejsu (HMI sterującego) dla użytkownika przeglądarki wybrano szablony i mechanizmy HTML sprzęgnięte natywnie z widokami w Django, wykorzystujące dogodnie strukturę dziedziczenia.

* **Wygenerowane zasady widoków na bazie HTML:**
  * Szablon master: **`base.html`** – plik stanowiący ogólnozakrojony szkielet strony operujący globalną strukturą powtarzaną oraz dołączonym arkuszem stylizujących kompozycji CSS.
  * Szablon zalogowanego panelu: **`dashboard.html`** - Główny hub powitalny autoryzowanego zarządcy, ukazujący szczegóły podpiętego konta wraz ze spreparowanymi kartami analitycznymi na pomiary. Ujawnia przycisk panelu sterowania, jeśli obecny stan przypisania usera pozwala na bycie `superuser`.
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


### `MODUŁ: KONCEPCJE DZIELONE – API / NODES /`

Zgodnie z ugruntowanymi specyfikacjami po fazie modelowania bazy parametrów z urządzeń z modułami raportującymi, stacja oczekuje następujących interfejsów (tzw. zarysu docelowych end-pointów):

| Planowana Metoda | Oczekiwana docelowa struktura Endpointa  | Rodzaj i Autoryzacja | Skonceptowany Wsad / Payload dla JSON |
|---|---|---|---|
| POST | `/api/nodes/telemetry/` | ✅ Ścisła z Poświadczeniem stacji | `{"node_id": "Pico_01", "temp": 24.5, "humidity": 60, "light": 850}` |
| GET | `/api/nodes/status/` | ✅ Potwierdzona sesja Webapp | Brak ładunku POST |
| POST | `/api/nodes/command/` | ✅ Webapp Bearer/Session | `{"target_node": "RPi_HQ", "command": ["WATER_PUMP_ON", "10_MIN"]}` |

---

## 5. Rozwój w przyszłości

Gdy ustalona zostanie ostateczna forma formatowania strukturalnego wektorowych plików zgłoszeń z centrali (na bazie podjętych schematów JSON wysyłanych z mikrokontrolerów przez sieć czy mostku MQTT / proxy HTTP):

1. **Konfiguracja Modeli:** Zmodyfikowanie wyizolowanej strefy backendowej wejść z jednostek zewnętrznych - uzupełnienie struktury relacyjnej `nodes/models.py`. 
2. **REST API i JSON:**  Podłączenie na podstawie tabel, oprogramowanych wizerunków `Serializer-ów` i widoków autoryzacyjnych, zgarniających wartości z tabeli poświadczeniowych z JSONów od sprzętu.
3. **Pulpit / Dashboard:**  Pobieranie zwrotnych informacji przez użytkownika uwierzytelnionego widoku z aplikacji web i zgaszenie tzw. place-holderów za sprawą wyświetlenia wyrenderowanych widoków tabel odczytywania statystyk nawodnienia w interfejsie przeglądarkowym dla szablonów statycznych.
4. **Alerty Discord (Opcjonalnie):** Jeśli zaimplementowane zostaną alerty powiadomień błędnych – system dośle je przez wejścia i procedury sieciowe WebHook do podjętego czatu społeczności bez zaangażowania bocznego użytkownika serwera lokalnego.
