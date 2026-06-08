import uasyncio as asyncio
from machine import ADC, Pin

class BaseSensor:
    """
    Abstrakcyjna klasa bazowa czujnika.
    Architektura projektu zakłada użycie wstrzykiwania zależności (Dependency Injection),
    aby umożliwić szybką podmianę modułów czujników bez modyfikacji pętli głównej.
    """
    async def read(self):
        raise NotImplementedError

class AnalogMoistureSensor(BaseSensor):
    """
    Czujnik wilgotności z wyjściem analogowym.
    Zgodnie z dokumentacją projektu, odczyt z czujnika odbywa się asynchronicznie,
    aby nie blokować obsługi sieci i komend MQTT.
    """
    def __init__(self, pin_number):
        self.adc = ADC(Pin(pin_number))

    async def read(self):
        # Yield dla event loopa – zapobiega blokowaniu przy szybkiej pętli
        await asyncio.sleep_ms(10)
        try:
            raw_val = self.adc.read_u16()
            # Normalizacja do 0.0–1.0 (0=mokro, 1=sucho)
            return round(raw_val / 65535.0, 4)
        except Exception as e:
            print(f"[Sensor] Blad odczytu ADC: {e}")
            return -1.0
