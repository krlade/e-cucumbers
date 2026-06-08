from machine import Pin
import uasyncio as asyncio
import config

class LedManager:
    def __init__(self):
        self.power_led = Pin(config.POWER_LED_PIN, Pin.OUT)
        self.status_led = Pin(config.STATUS_LED_PIN, Pin.OUT)
        self.power_led.value(1) # Zasilanie świeci ciągle
        self.status_led.value(0)
        self._status = 'no_wifi'

    def set_status(self, status):
        self._status = status

    async def run(self):
        while True:
            if self._status == 'no_wifi':
                self.status_led.value(0)
                await asyncio.sleep(0.5)
            elif self._status == 'connecting_mqtt':
                self.status_led.value(1)
                await asyncio.sleep(0.2)
                self.status_led.value(0)
                await asyncio.sleep(0.2)
            elif self._status == 'connected':
                self.status_led.value(1)
                await asyncio.sleep(0.5)
            else:
                await asyncio.sleep(0.5)
