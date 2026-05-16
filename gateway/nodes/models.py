import datetime
from django.db import models
from django.utils import timezone


class Node(models.Model):
    """
    Formalny model urządzenia (węzła sensorycznego) w sieci IoT.
    Dane są synchronizowane z in-memory obiektu Device przez klienta MQTT.
    """
    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Nazwa węzła",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Zarejestrowano",
    )
    last_seen = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Ostatnia transmisja",
        help_text="Czas ostatniej odebranej ramki MQTT od tego urządzenia.",
    )
    is_sending = models.BooleanField(
        default=False,
        verbose_name="Nadaje dane",
    )
    delay_ms = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="Interwał transmisji [ms]",
    )
    pins = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Stan pinów GPIO",
        help_text="Słownik {numer_pinu: wartość} odzwierciedlający aktualny stan wyjść GPIO.",
    )
    last_data = models.JSONField(
        null=True,
        blank=True,
        verbose_name="Ostatnie dane pomiarowe",
        help_text="Ostatni payload odebrany na topic /device/<name>/data.",
    )
    
    # Pojedynczy pin pomiarowy węzła
    sensor_pin = models.IntegerField(null=True, blank=True, verbose_name="Pin sensoryczny")
    sensor_type = models.CharField(max_length=50, blank=True, null=True, verbose_name="Typ pomiaru")
    sensor_unit = models.CharField(max_length=20, blank=True, null=True, verbose_name="Jednostka")
    sensor_min_value = models.FloatField(blank=True, null=True, verbose_name="Wartość min")
    sensor_max_value = models.FloatField(blank=True, null=True, verbose_name="Wartość max")
    sensor_last_value = models.CharField(max_length=255, blank=True, null=True, verbose_name="Ostatnia wartość")

    class Meta:
        verbose_name = "Węzeł"
        verbose_name_plural = "Węzły"
        ordering = ["-last_seen"]

    def __str__(self):
        return self.name

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    ONLINE_THRESHOLD = datetime.timedelta(minutes=5)

    @property
    def is_online(self) -> bool:
        """True jeśli ostatnia transmisja była nie dalej niż 5 minut temu."""
        if not self.last_seen:
            return False
        return (timezone.now() - self.last_seen) < self.ONLINE_THRESHOLD

    @property
    def last_seen_ago(self) -> str:
        """Czytelna forma czasu od ostatniej transmisji, np. '3 min temu'."""
        if not self.last_seen:
            return "nigdy"
        delta = timezone.now() - self.last_seen
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return f"{seconds} s temu"
        if seconds < 3600:
            return f"{seconds // 60} min temu"
        if seconds < 86400:
            return f"{seconds // 3600} h temu"
        return f"{seconds // 86400} d temu"


# Komendy dostępne w schedulerze (bez argumentu / z argumentem int)
SCHEDULABLE_COMMANDS_NO_ARG = ["set_on", "set_off", "echo", "get_pins"]
SCHEDULABLE_COMMANDS_INT_ARG = ["pin_on", "pin_off", "change_delay", "get_format"]
SCHEDULABLE_COMMANDS = SCHEDULABLE_COMMANDS_NO_ARG + SCHEDULABLE_COMMANDS_INT_ARG


class ScheduledCommand(models.Model):
    """
    Zaplanowane (cykliczne) wywołanie komendy MQTT dla danego węzła.
    Scheduler wykonuje komendę co `interval_seconds` sekund.
    """
    node_name = models.CharField(
        max_length=100,
        verbose_name="Węzeł",
        db_index=True,
    )
    command = models.CharField(
        max_length=50,
        verbose_name="Komenda",
        choices=[(c, c) for c in SCHEDULABLE_COMMANDS],
    )
    argument = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="Argument (int)",
        help_text="Wymagany dla: pin_on, pin_off, change_delay, get_format.",
    )
    interval_seconds = models.PositiveIntegerField(
        verbose_name="Interwał [s]",
        help_text="Co ile sekund komenda ma być wysyłana.",
    )
    enabled = models.BooleanField(
        default=True,
        verbose_name="Aktywny",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_run = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Ostatnie uruchomienie",
    )

    class Meta:
        verbose_name = "Zaplanowana komenda"
        verbose_name_plural = "Zaplanowane komendy"
        ordering = ["node_name", "command"]

    def __str__(self):
        arg_str = f"({self.argument})" if self.argument is not None else ""
        return f"{self.node_name} › {self.command}{arg_str} co {self.interval_seconds}s"


class GatewayToken(models.Model):
    """
    Model do przechowywania tokenów JWT gatewaya (access i refresh).
    Gateway jest jeden, więc używamy tylko jednego rekordu.
    """
    access = models.TextField(blank=True, null=True, verbose_name="Access Token")
    refresh = models.TextField(blank=True, null=True, verbose_name="Refresh Token")
    device_id = models.CharField(max_length=100, blank=True, null=True, verbose_name="Device ID")

    class Meta:
        verbose_name = "Token Gatewaya"
        verbose_name_plural = "Tokeny Gatewaya"

    def __str__(self):
        return f"Token Gatewaya ({self.device_id or 'Brak ID'})"

    @classmethod
    def get_tokens(cls):
        obj, _ = cls.objects.get_or_create(id=1)
        if obj.access and obj.refresh:
            return {"access": obj.access, "refresh": obj.refresh, "device_id": obj.device_id}
        return None

    @classmethod
    def save_tokens(cls, tokens, device_id=None):
        obj, _ = cls.objects.get_or_create(id=1)
        if "access" in tokens:
            obj.access = tokens["access"]
        if "refresh" in tokens:
            obj.refresh = tokens["refresh"]
        if device_id is not None:
            obj.device_id = device_id
        obj.save()

