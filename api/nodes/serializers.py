from rest_framework import serializers
from .models import PairingToken, CentralUnit


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
        if CentralUnit.objects.filter(device_id=value).exists():
            raise serializers.ValidationError("Device with this ID is already registered.")
        return value
