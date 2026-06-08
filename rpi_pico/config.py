import json

# Nazwa urządzenia
NAME = "PICO"

# Broker MQTT
MQTT_BROKER = "mqtt.krlade.dev"
MQTT_PORT = 443
MQTT_USER = "user"
MQTT_PASSWORD = "ogorek123!"

# Domyślne dane Station (klient)
DEFAULT_STA_SSID = "test"
DEFAULT_STA_PASSWORD = ""

# Domyślne dane Access Point
DEFAULT_AP_SSID = NAME
DEFAULT_AP_PASSWORD = ""

# Piny
POWER_LED_PIN = 0  # GP0 – dioda zasilania (świeci ciągle)
STATUS_LED_PIN = 1 # GP1 – dioda statusu (no_wifi/connecting/connected)

# Pin przycisku konfiguracyjnego.
# Podłączenie: 3.3V → przycisk → GP15. Wewnętrzny pull-down gwarantuje
# stan niski gdy przycisk puszczony, stan wysoki (1) gdy wciśnięty.
CONFIG_BUTTON_PIN = 15

# Piny dopuszczone do sterowania przez komendy pin_on / pin_off
ALLOWED_PINS = [3, 4, 5]

# Czujnik wilgotności – analogowe wejście ADC1 (GP27)
MOISTURE_ADC_PIN = 27

# Format danych wysyłanych przez czujnik wilgotności.
# Odczyt jest normalizowany do zakresu 0.0–1.0 (float), gdzie
# 0.0 oznacza całkowite nasycenie wodą, a 1.0 – całkowite wyschnięcie.
SENSOR_FORMAT = json.dumps({
    "type": "float",
    "min": 0.0,
    "max": 1.0,
    "unit": "%"
})
