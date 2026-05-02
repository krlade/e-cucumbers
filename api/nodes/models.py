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
    """Urządzenie peryferyjne podłączone do pinu GPIO Jednostki Centralnej."""

    TYPE_LAMP = "LAMP"
    TYPE_SPRINKLER = "SPRINKLER"
    TYPE_CHOICES = [
        (TYPE_LAMP, "Lampa"),
        (TYPE_SPRINKLER, "Zraszacz"),
    ]

    # Legalne komendy per typ urządzenia.
    # params=[] oznacza brak wymaganego parametru; params z "key":"time" oznacza wymagany czas.
    COMMANDS = {
        TYPE_LAMP: [
            {"name": "TURN_ON",     "params": []},
            {"name": "TURN_OFF",    "params": []},
            {"name": "TURN_ON_FOR", "params": [{"key": "time", "unit": "minutes", "type": "int"}]},
        ],
        TYPE_SPRINKLER: [
            {"name": "WATER_PUMP_ON", "params": [{"key": "time", "unit": "minutes", "type": "int"}]},
        ],
    }

    gateway = models.ForeignKey(
        CentralUnit, on_delete=models.CASCADE, related_name="peripherals"
    )
    node_id = models.CharField(max_length=64, help_text="ID węzła końcowego, np. 'Pico_01'")
    gpio = models.PositiveSmallIntegerField(help_text="Numer pinu GPIO")
    peripheral_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    registered_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("gateway", "node_id", "gpio")

    @property
    def allowed_commands(self):
        return self.COMMANDS.get(self.peripheral_type, [])

    def __str__(self):
        return f"{self.peripheral_type} @ {self.gateway.device_id}/{self.node_id} GPIO{self.gpio}"


class QueuedCommand(models.Model):
    """Polecenie zakolejkowane przez użytkownika, oczekujące na odebranie przez gateway (heartbeat)."""

    STATUS_PENDING = "pending"
    STATUS_DELIVERED = "delivered"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Oczekujące"),
        (STATUS_DELIVERED, "Dostarczone"),
    ]

    peripheral = models.ForeignKey(
        ControllableNode, on_delete=models.CASCADE, related_name="queued_commands"
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="issued_commands"
    )
    command = models.CharField(max_length=32, help_text="Nazwa komendy, np. 'TURN_ON_FOR'")
    # Czas jako opcjonalny parametr (godziny dla lamp, minuty dla zraszaczy)
    time = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        param = f" time={self.time}" if self.time is not None else ""
        return f"{self.command}{param} -> {self.peripheral} [{self.status}]"
