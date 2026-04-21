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
