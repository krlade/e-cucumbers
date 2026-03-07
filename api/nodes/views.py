from django.contrib.auth.models import User
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import CentralUnit, DeviceOwnership, PairingToken
from .serializers import PairingTokenResponseSerializer, RegisterDeviceSerializer


class CreatePairingTokenView(APIView):
    """POST /api/nodes/pairing-token/ — generuje token parowania (wymaga JWT)."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        token = PairingToken.generate(owner=request.user)
        serializer = PairingTokenResponseSerializer(token)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class RegisterDeviceView(APIView):
    """POST /api/nodes/register-device/ — rejestracja Jednostki Centralnej za pomocą pairing tokenu."""

    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = RegisterDeviceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        device_id = serializer.validated_data["device_id"]
        token_str = serializer.validated_data["pairing_token"]

        # Fetch and consume pairing token
        pairing_token = PairingToken.objects.get(token=token_str)
        owner = pairing_token.owner

        # Create system user for the device (for JWT generation)
        device_username = f"device_{device_id}"
        device_user = User.objects.create_user(
            username=device_username,
            password=None,  # no password login — JWT only
            is_active=True,
        )
        device_user.set_unusable_password()
        device_user.save()

        # Register the Central Unit
        unit = CentralUnit.objects.create(
            device_id=device_id,
            device_user=device_user,
        )

        # Grant admin ownership to the pairing token owner
        DeviceOwnership.objects.create(
            user=owner,
            device=unit,
            role=DeviceOwnership.ROLE_ADMIN,
        )

        # Delete the consumed pairing token
        pairing_token.delete()

        # Generate JWT for the device
        refresh = RefreshToken.for_user(device_user)

        return Response(
            {
                "device_id": device_id,
                "owner": owner.username,
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
            status=status.HTTP_200_OK,
        )
