from rest_framework import serializers
from .models import PairingToken, CentralUnit, ControllableNode, QueuedCommand


class PairingTokenResponseSerializer(serializers.ModelSerializer):
    expires_in_seconds = serializers.SerializerMethodField()

    class Meta:
        model = PairingToken
        fields = ["token", "expires_at", "expires_in_seconds"]

    def get_expires_in_seconds(self, obj):
        from django.utils import timezone
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
        # Ownership verification happens in the view.
        return value


# ── Peripherals ──

class PeripheralSerializer(serializers.ModelSerializer):
    allowed_commands = serializers.ReadOnlyField()

    class Meta:
        model = ControllableNode
        fields = ["id", "node_id", "gpio", "peripheral_type", "allowed_commands", "updated_at"]
        read_only_fields = fields


class RegisterPeripheralItemSerializer(serializers.Serializer):
    node_id = serializers.CharField(max_length=64)
    gpio = serializers.IntegerField(min_value=0, max_value=40)
    peripheral_type = serializers.ChoiceField(choices=ControllableNode.TYPE_CHOICES)


class RegisterPeripheralsSerializer(serializers.Serializer):
    device_id = serializers.CharField(max_length=64)
    peripherals = RegisterPeripheralItemSerializer(many=True, min_length=1)

    def validate_device_id(self, value):
        if not CentralUnit.objects.filter(device_id=value).exists():
            raise serializers.ValidationError("Device not found.")
        return value


# ── Commands ──

class SendCommandSerializer(serializers.Serializer):
    """Payload komendy wysyłanej przez użytkownika do urządzenia peryferyjnego.

    Format zgodny z User Story:
        {"device_id": "2137", "node_id": "Pico_01", "gpio": 1, "command": ["TURN_ON_FOR", 8]}
        {"device_id": "2137", "node_id": "Pico_01", "gpio": 2, "command": ["WATER_PUMP_ON", 45]}
        {"device_id": "2137", "node_id": "Pico_01", "gpio": 1, "command": ["TURN_OFF"]}
    """
    device_id = serializers.CharField(max_length=64)
    node_id = serializers.CharField(max_length=64)
    gpio = serializers.IntegerField(min_value=0, max_value=40)
    command = serializers.ListField(
        child=serializers.JSONField(),
        min_length=1,
        max_length=2,
    )

    def validate(self, data):
        # 1. Sprawdź czy peripheral istnieje
        try:
            gateway = CentralUnit.objects.get(device_id=data["device_id"])
        except CentralUnit.DoesNotExist:
            raise serializers.ValidationError({"device_id": "Device not found."})

        try:
            peripheral = ControllableNode.objects.get(
                gateway=gateway,
                node_id=data["node_id"],
                gpio=data["gpio"],
            )
        except ControllableNode.DoesNotExist:
            raise serializers.ValidationError(
                {"gpio": f"No peripheral registered at node '{data['node_id']}' GPIO {data['gpio']}."}
            )

        # 2. Sprawdź czy command[0] jest legalną komendą dla tego typu
        cmd_name = data["command"][0]
        if not isinstance(cmd_name, str):
            raise serializers.ValidationError({"command": "Command name must be a string."})

        allowed = {c["name"]: c for c in peripheral.allowed_commands}
        if cmd_name not in allowed:
            raise serializers.ValidationError(
                {"command": f"'{cmd_name}' is not a valid command for {peripheral.peripheral_type}. "
                            f"Allowed: {list(allowed.keys())}"}
            )

        # 3. Sprawdź parametr czasu jeśli komenda go wymaga
        cmd_def = allowed[cmd_name]
        requires_time = any(p["key"] == "time" for p in cmd_def["params"])

        if requires_time:
            if len(data["command"]) < 2:
                raise serializers.ValidationError(
                    {"command": f"'{cmd_name}' requires a time parameter as the second element."}
                )
            time_val = data["command"][1]
            if not isinstance(time_val, int) or time_val <= 0:
                raise serializers.ValidationError(
                    {"command": "Time parameter must be a positive integer."}
                )
        else:
            if len(data["command"]) > 1:
                raise serializers.ValidationError(
                    {"command": f"'{cmd_name}' does not accept a time parameter."}
                )

        # Attach resolved objects for use in the view
        data["_peripheral"] = peripheral
        data["_cmd_name"] = cmd_name
        data["_time"] = data["command"][1] if requires_time else None
        return data


class QueuedCommandSerializer(serializers.ModelSerializer):
    peripheral_type = serializers.CharField(source="peripheral.peripheral_type", read_only=True)
    node_id = serializers.CharField(source="peripheral.node_id", read_only=True)
    gpio = serializers.IntegerField(source="peripheral.gpio", read_only=True)

    class Meta:
        model = QueuedCommand
        fields = ["id", "node_id", "gpio", "peripheral_type", "command", "time", "status", "created_at"]
        read_only_fields = fields
