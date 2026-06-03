import random

from django.conf import settings
from django.db import models
from django.utils import timezone
from datetime import timedelta


class PairingToken(models.Model):
    """Tymczasowy token parowania urządzenia z kontem użytkownika."""

    token = models.CharField(max_length=16, unique=True, db_index=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pairing_tokens"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    VALIDITY_MINUTES = 15

    def is_valid(self):
        return timezone.now() < self.expires_at

    @classmethod
    def generate(cls, owner):
        """Create a new pairing token for the given user."""
        code = f"TEMP-{random.randint(1000, 9999)}"
        while cls.objects.filter(token=code).exists():
            code = f"TEMP-{random.randint(1000, 9999)}"
        return cls.objects.create(
            token=code,
            owner=owner,
            expires_at=timezone.now() + timedelta(minutes=cls.VALIDITY_MINUTES),
        )

    def __str__(self):
        return f"{self.token} (owner={self.owner.username})"


class CentralUnit(models.Model):
    """Jednostka Centralna (np. Raspberry Pi) zarejestrowana w systemie."""

    device_id = models.CharField(max_length=64, unique=True, db_index=True)
    device_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="central_unit",
        help_text="Systemowe konto User powiązane z urządzeniem (do generowania JWT).",
    )
    registered_at = models.DateTimeField(auto_now_add=True)
    last_heartbeat = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Czas ostatniego heartbeatu od Gateway.",
    )

    ONLINE_THRESHOLD = timedelta(seconds=30)

    @property
    def is_online(self) -> bool:
        """True jeśli ostatni heartbeat był nie dalej niż 30 sekund temu."""
        if not self.last_heartbeat:
            return False
        return (timezone.now() - self.last_heartbeat) < self.ONLINE_THRESHOLD

    def __str__(self):
        return f"CentralUnit {self.device_id}"


class DeviceOwnership(models.Model):
    """Relacja właściciel/współdzielenie: kto ma dostęp do jakiego urządzenia i z jaką rolą."""

    ROLE_ADMIN = "admin"
    ROLE_VIEWER = "viewer"
    ROLE_CHOICES = [
        (ROLE_ADMIN, "Administrator"),
        (ROLE_VIEWER, "Viewer"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="device_ownerships"
    )
    device = models.ForeignKey(
        CentralUnit, on_delete=models.CASCADE, related_name="ownerships"
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_ADMIN)

    class Meta:
        unique_together = ("user", "device")

    def __str__(self):
        return f"{self.user.username} -> {self.device.device_id} ({self.role})"


class ControllableNode(models.Model):
    """Węzeł końcowy (np. Pico) podłączony do Jednostki Centralnej.

    Służy jako opcjonalna warstwa konfiguracyjna — użytkownik może nadać etykietę
    i przypisać typ czujnika do węzła po tym jak dane zaczną napływać.
    Nie jest wymagany do wysyłania komend ani odbierania telemetrii.
    """

    TYPE_LAMP = "LAMP"
    TYPE_SPRINKLER = "SPRINKLER"
    TYPE_CHOICES = [
        (TYPE_LAMP, "Lampa"),
        (TYPE_SPRINKLER, "Zraszacz"),
    ]

    SENSOR_TEMPERATURE = "temperature"
    SENSOR_HUMIDITY    = "humidity"
    SENSOR_LIGHT       = "light"
    SENSOR_CHOICES = [
        (SENSOR_TEMPERATURE, "Temperatura (°C)"),
        (SENSOR_HUMIDITY,    "Wilgotność (%)"),
        (SENSOR_LIGHT,       "Natężenie światła (lux)"),
    ]

    # Legalne komendy per typ urządzenia.
    COMMANDS = {
        TYPE_LAMP: [
            {"name": "TURN_ON",     "params": []},
            {"name": "TURN_OFF",    "params": []},
            {"name": "TURN_ON_FOR", "params": [{"key": "time", "unit": "minutes", "type": "int"}]},
        ],
        TYPE_SPRINKLER: [
            {"name": "WATER_PUMP_ON", "params": [{"key": "time", "unit": "minutes", "type": "int"}]},
            {"name": "TURN_OFF",    "params": []},
        ],
    }

    gateway = models.ForeignKey(
        CentralUnit, on_delete=models.CASCADE, related_name="peripherals"
    )
    node_id = models.CharField(max_length=64, help_text="ID węzła końcowego, np. 'Pico_01'")
    gpio = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Numer pinu GPIO (tylko dla węzłów sterowanych)"
    )
    peripheral_type = models.CharField(
        max_length=16, choices=TYPE_CHOICES, null=True, blank=True
    )
    sensor_type = models.CharField(
        max_length=16, choices=SENSOR_CHOICES, null=True, blank=True,
        help_text="Typ czujnika przypisany przez użytkownika."
    )
    label = models.CharField(
        max_length=100, null=True, blank=True,
        help_text="Przyjazna nazwa urządzenia nadana przez użytkownika, np. 'Lampa nad rozsadą'.",
    )
    registered_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("gateway", "node_id")

    @property
    def allowed_commands(self):
        return self.COMMANDS.get(self.peripheral_type, [])

    @property
    def display_name(self):
        """Zwraca etykietę jeśli istnieje, w przeciwnym razie node_id."""
        return self.label or self.node_id

    def __str__(self):
        parts = []
        if self.peripheral_type:
            parts.append(f"{self.peripheral_type} GPIO{self.gpio}")
        if self.sensor_type:
            parts.append(f"sensor={self.sensor_type}")
        desc = ", ".join(parts) or "no role"
        return f"[{desc}] @ {self.gateway.device_id}/{self.node_id}"


class QueuedCommand(models.Model):
    """Polecenie zakolejkowane przez użytkownika, oczekujące na odebranie przez gateway (heartbeat).

    Kierowane bezpośrednio do gateway (CentralUnit) z informacją o węźle i pinie GPIO.
    Nie wymaga pre-rejestracji węzła w ControllableNode.
    """

    STATUS_PENDING = "pending"
    STATUS_DELIVERED = "delivered"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Oczekujące"),
        (STATUS_DELIVERED, "Dostarczone"),
    ]

    COMMAND_TURN_ON = "TURN_ON"
    COMMAND_TURN_OFF = "TURN_OFF"
    COMMAND_TURN_ON_FOR = "TURN_ON_FOR"
    COMMAND_WATER_PUMP_ON = "WATER_PUMP_ON"
    COMMAND_CHOICES = [
        (COMMAND_TURN_ON, "Włącz"),
        (COMMAND_TURN_OFF, "Wyłącz"),
        (COMMAND_TURN_ON_FOR, "Włącz na czas"),
        (COMMAND_WATER_PUMP_ON, "Nawadniaj przez czas"),
    ]

    gateway = models.ForeignKey(
        CentralUnit, on_delete=models.CASCADE, related_name="queued_commands",
        help_text="Gateway do którego kierowana jest komenda."
    )
    node_id = models.CharField(max_length=64, help_text="ID węzła Pico, np. 'Pico_01'")
    gpio = models.PositiveSmallIntegerField(help_text="Numer pinu GPIO")
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="issued_commands"
    )
    command = models.CharField(max_length=32, choices=COMMAND_CHOICES, help_text="Nazwa komendy")
    time = models.PositiveIntegerField(null=True, blank=True, help_text="Czas trwania w minutach (opcjonalny)")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        param = f" time={self.time}" if self.time is not None else ""
        return f"{self.command}{param} -> {self.gateway.device_id}/{self.node_id} GPIO{self.gpio} [{self.status}]"


class TelemetryReading(models.Model):
    """Odczyt z węzła końcowego przekazany przez Gateway.

    Gateway przesyła surowy payload tak jak dostał od węzła Pico.
    Użytkownik konfiguruje interpretację (sensor_type) po tym jak dane zaczną napływać.
    Rekordy są tylko dopisywane (append-only) — nigdy nie nadpisywane.
    """

    SENSOR_TEMPERATURE = "temperature"
    SENSOR_HUMIDITY    = "humidity"
    SENSOR_LIGHT       = "light"
    SENSOR_CHOICES = [
        (SENSOR_TEMPERATURE, "Temperatura (°C)"),
        (SENSOR_HUMIDITY,    "Wilgotność (%)"),
        (SENSOR_LIGHT,       "Natężenie światła (lux)"),
    ]

    gateway     = models.ForeignKey(
        CentralUnit, on_delete=models.CASCADE, related_name="telemetry_readings"
    )
    node_id     = models.CharField(max_length=64, help_text="ID węzła, np. 'Pico_01'")
    # Surowy payload przesłany przez Gateway, tak jak dostał od węzła Pico
    raw_payload = models.JSONField(
        null=True, blank=True,
        help_text="Surowy payload z węzła Pico, np. {\"data\": 23.5}",
    )
    # Wyekstrahowana wartość liczbowa (dla wykresów i filtrowania)
    value       = models.FloatField(null=True, blank=True)
    # Typ czujnika — opcjonalny, konfigurowany przez użytkownika po rejestracji węzła
    sensor_type = models.CharField(
        max_length=16, choices=SENSOR_CHOICES, null=True, blank=True,
        help_text="Typ czujnika. Pobierany z konfiguracji węzła (ControllableNode), jeśli węzeł jest skonfigurowany.",
    )
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at"]
        indexes = [
            models.Index(fields=["gateway", "node_id", "-recorded_at"]),
        ]

    def __str__(self):
        sensor_info = f" [{self.sensor_type}]" if self.sensor_type else ""
        return f"{self.node_id}{sensor_info}={self.value} @ {self.gateway.device_id}"
