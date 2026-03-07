import random
import string

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
        # Ensure uniqueness
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
