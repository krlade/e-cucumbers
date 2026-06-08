from django.utils import timezone
from rest_framework import serializers
from .models import PairingToken, CentralUnit, ControllableNode, QueuedCommand, TelemetryReading


class PairingTokenResponseSerializer(serializers.ModelSerializer):
    expires_in_seconds = serializers.SerializerMethodField()

    class Meta:
        model = PairingToken
        fields = ["token", "expires_at", "expires_in_seconds"]

    def get_expires_in_seconds(self, obj):
        delta = obj.expires_at - timezone.now()
        return max(0, int(delta.total_seconds()))


class RegisterDeviceSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=64)
    pairing_token = serializers.CharField(max_length=16)

    def validate_pairing_token(self, value):
        try:
            token_obj = PairingToken.objects.get(token=value)
        except PairingToken.DoesNotExist:
            raise serializers.ValidationError("Pairing token does not exist.")
        if not token_obj.is_valid():
            token_obj.delete()
            raise serializers.ValidationError("Pairing token has expired.")
        return value

    def validate_device_id(self, value):
        # Uniqueness is NOT enforced here — re-registration by the original
        # owner (after a factory reset) is a valid and supported scenario.
        return value


# ── Peripherals (optional node config layer) ──

class PeripheralSerializer(serializers.ModelSerializer):
    allowed_commands = serializers.ReadOnlyField()
    display_name = serializers.ReadOnlyField()

    class Meta:
        model = ControllableNode
        fields = [
            "id", "node_id", "gpio", "peripheral_type", "sensor_type",
            "label", "display_name", "allowed_commands", "updated_at", "is_active",
        ]
        read_only_fields = fields


class NodeConfigSerializer(serializers.Serializer):
    """Payload do konfiguracji węzła przez użytkownika — nadanie etykiety i typu czujnika."""
    device_id = serializers.CharField(max_length=64)
    node_id = serializers.CharField(max_length=64)
    label = serializers.CharField(max_length=100, required=False, allow_null=True, allow_blank=True)
    sensor_type = serializers.ChoiceField(
        choices=ControllableNode.SENSOR_CHOICES, required=False, allow_null=True
    )
    gpio = serializers.IntegerField(min_value=0, max_value=40, required=False, allow_null=True)
    peripheral_type = serializers.ChoiceField(
        choices=ControllableNode.TYPE_CHOICES, required=False, allow_null=True
    )


class RegisterPeripheralItemSerializer(serializers.Serializer):
    node_id = serializers.CharField(max_length=64)
    gpio = serializers.IntegerField(min_value=0, max_value=40, required=False, allow_null=True)
    peripheral_type = serializers.ChoiceField(
        choices=ControllableNode.TYPE_CHOICES, required=False, allow_null=True
    )
    sensor_type = serializers.ChoiceField(
        choices=ControllableNode.SENSOR_CHOICES, required=False, allow_null=True
    )

    def validate(self, data):
        has_peripheral = data.get("gpio") is not None and data.get("peripheral_type") is not None
        has_sensor = data.get("sensor_type") is not None
        if not has_peripheral and not has_sensor:
            raise serializers.ValidationError(
                "Każdy węzeł musi mieć co najmniej czujnik (sensor_type) lub urządzenie sterowane (gpio + peripheral_type)."
            )
        if (data.get("gpio") is None) != (data.get("peripheral_type") is None):
            raise serializers.ValidationError(
                "Pola gpio i peripheral_type muszą być podane razem lub oba pominięte."
            )
        return data


class RegisterPeripheralsSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=64)
    peripherals = RegisterPeripheralItemSerializer(many=True, min_length=1)

    def validate_device_id(self, value):
        if not CentralUnit.objects.filter(device_id=value).exists():
            raise serializers.ValidationError("Device not found.")
        return value

    def validate(self, data):
        peripherals = data.get("peripherals", [])
        node_ids = [p["node_id"] for p in peripherals]
        if len(node_ids) != len(set(node_ids)):
            raise serializers.ValidationError(
                {"peripherals": "Każdy węzeł (node_id) w liście musi mieć unikalną nazwę."}
            )
        return data


# ── Commands ──

class SendCommandSerializer(serializers.Serializer):
    """Payload komendy wysyłanej przez użytkownika do węzła pico.

    Format KISS — tylko co, gdzie i ewentualnie jak długo:
        {"device_id": "2137", "node_id": "Pico_01", "gpio": 1, "command": ["TURN_ON"]}
        {"device_id": "2137", "node_id": "Pico_01", "gpio": 1, "command": ["TURN_ON_FOR", 8]}
        {"device_id": "2137", "node_id": "Pico_02", "gpio": 2, "command": ["WATER_PUMP_ON", 15]}
        {"device_id": "2137", "node_id": "Pico_01", "gpio": 1, "command": ["TURN_OFF"]}

    Nie wymaga pre-rejestracji węzła — komendy węzeł/gpio mogą być dowolne.
    """
    device_id = serializers.CharField(max_length=64)
    node_id = serializers.CharField(max_length=64)
    gpio = serializers.IntegerField(min_value=0, max_value=40)
    command = serializers.ListField(
        child=serializers.JSONField(),
        min_length=1,
        max_length=2,
    )

    # Legalne komendy i czy wymagają czasu
    _TIMED_COMMANDS = {"TURN_ON_FOR", "WATER_PUMP_ON"}
    _ALL_COMMANDS = {"TURN_ON", "TURN_OFF", "TURN_ON_FOR", "WATER_PUMP_ON"}

    def validate(self, data):
        # Sprawdź czy device_id istnieje
        try:
            gateway = CentralUnit.objects.get(device_id=data["device_id"])
        except CentralUnit.DoesNotExist:
            raise serializers.ValidationError({"device_id": "Device not found."})

        cmd_name = data["command"][0]
        if not isinstance(cmd_name, str):
            raise serializers.ValidationError({"command": "Command name must be a string."})

        if cmd_name not in self._ALL_COMMANDS:
            raise serializers.ValidationError(
                {"command": f"'{cmd_name}' is not a valid command. Allowed: {sorted(self._ALL_COMMANDS)}"}
            )

        requires_time = cmd_name in self._TIMED_COMMANDS

        if requires_time:
            if len(data["command"]) < 2:
                raise serializers.ValidationError(
                    {"command": f"'{cmd_name}' requires a time parameter as the second element."}
                )
            time_val = data["command"][1]
            if not isinstance(time_val, int) or time_val <= 0:
                raise serializers.ValidationError(
                    {"command": "Time parameter must be a positive integer (minutes)."}
                )
        else:
            if len(data["command"]) > 1:
                raise serializers.ValidationError(
                    {"command": f"'{cmd_name}' does not accept a time parameter."}
                )

        data["_gateway"] = gateway
        data["_cmd_name"] = cmd_name
        data["_time"] = data["command"][1] if requires_time else None
        return data


class QueuedCommandSerializer(serializers.ModelSerializer):
    """Serializacja komendy z historii. Zawiera czytelny opis po ludzku."""
    human_description = serializers.SerializerMethodField()

    class Meta:
        model = QueuedCommand
        fields = [
            "id", "node_id", "gpio", "command", "time",
            "status", "created_at", "delivered_at", "human_description",
        ]
        read_only_fields = fields

    def get_human_description(self, obj) -> str:
        """Zamienia techniczną komendę na czytelny opis dla użytkownika."""
        if obj.command == "TURN_ON":
            return "Włączono"
        elif obj.command == "TURN_OFF":
            return "Wyłączono"
        elif obj.command == "TURN_ON_FOR":
            return f"Włączono na {obj.time} min"
        elif obj.command == "WATER_PUMP_ON":
            return f"Nawadnianie przez {obj.time} min"
        return obj.command


# ── Telemetry ──

class TelemetrySerializer(serializers.Serializer):
    """Payload wysyłany przez Gateway z surowym odczytem węzła Pico.

    Gateway przekazuje dane 1:1 tak jak dostał od węzła.
    Węzeł Pico wysyła: {"data": 23.5}
    Gateway przesyła do Webapp: {"node_id": "Pico_01", "payload": {"data": 23.5}}

    sensor_type jest pobierany automatycznie z konfiguracji węzła (ControllableNode),
    jeśli węzeł jest skonfigurowany przez użytkownika. W przeciwnym razie odczyt
    jest zapisywany bez typu czujnika.
    """
    node_id = serializers.CharField(max_length=64)
    payload = serializers.DictField(
        child=serializers.JSONField(),
        help_text="Surowy payload z węzła Pico, np. {\"data\": 23.5}",
    )


class TelemetryReadingSerializer(serializers.ModelSerializer):
    """Odpowiedź po zapisaniu odczytu + odpowiedź przy pobieraniu historii."""
    class Meta:
        model  = TelemetryReading
        fields = ["id", "node_id", "sensor_type", "value", "raw_payload", "recorded_at"]
        read_only_fields = fields


# ── Devices list ──

class DeviceListSerializer(serializers.ModelSerializer):
    """Urządzenie z informacją o statusie online."""
    is_online = serializers.ReadOnlyField()

    class Meta:
        model = CentralUnit
        fields = ["device_id", "registered_at", "last_heartbeat", "is_online"]
        read_only_fields = fields
