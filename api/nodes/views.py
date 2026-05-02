from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import CentralUnit, ControllableNode, DeviceOwnership, PairingToken, QueuedCommand
from .serializers import (
    PeripheralSerializer,
    PairingTokenResponseSerializer,
    QueuedCommandSerializer,
    RegisterDeviceSerializer,
    RegisterPeripheralsSerializer,
    SendCommandSerializer,
)


class CreatePairingTokenView(APIView):
    """POST /api/nodes/pairing-token/"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        token = PairingToken.generate(owner=request.user)
        return Response(PairingTokenResponseSerializer(token).data, status=status.HTTP_201_CREATED)


class RegisterDeviceView(APIView):
    """POST /api/nodes/register-device/"""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = RegisterDeviceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        device_id = serializer.validated_data["device_id"]
        token_str = serializer.validated_data["pairing_token"]

        pairing_token = PairingToken.objects.get(token=token_str)
        owner = pairing_token.owner
        existing_unit = CentralUnit.objects.filter(device_id=device_id).first()

        if existing_unit:
            is_admin = DeviceOwnership.objects.filter(
                user=owner, device=existing_unit, role=DeviceOwnership.ROLE_ADMIN
            ).exists()
            if not is_admin:
                pairing_token.delete()
                return Response({"detail": "You are not an admin of this device."}, status=status.HTTP_403_FORBIDDEN)
            pairing_token.delete()
            refresh = RefreshToken.for_user(existing_unit.device_user)
            return Response({
                "device_id": device_id, "owner": owner.username,
                "access": str(refresh.access_token), "refresh": str(refresh),
            }, status=status.HTTP_200_OK)

        device_user = User.objects.create_user(username=f"device_{device_id}", password=None, is_active=True)
        device_user.set_unusable_password()
        device_user.save()
        unit = CentralUnit.objects.create(device_id=device_id, device_user=device_user)
        DeviceOwnership.objects.create(user=owner, device=unit, role=DeviceOwnership.ROLE_ADMIN)
        pairing_token.delete()

        refresh = RefreshToken.for_user(device_user)
        return Response({
            "device_id": device_id, "owner": owner.username,
            "access": str(refresh.access_token), "refresh": str(refresh),
        }, status=status.HTTP_200_OK)


class RegisterPeripheralsView(APIView):
    """POST /api/nodes/register-peripherals/ — gateway rejestruje peryferia (wymaga JWT urządzenia)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = RegisterPeripheralsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        device_id = serializer.validated_data["device_id"]
        peripherals_data = serializer.validated_data["peripherals"]

        try:
            gateway = CentralUnit.objects.get(device_id=device_id)
        except CentralUnit.DoesNotExist:
            return Response({"detail": "Device not found."}, status=status.HTTP_404_NOT_FOUND)

        if gateway.device_user != request.user:
            return Response({"detail": "JWT does not belong to this device."}, status=status.HTTP_403_FORBIDDEN)

        registered = []
        for p in peripherals_data:
            obj, _ = ControllableNode.objects.update_or_create(
                gateway=gateway, node_id=p["node_id"], gpio=p["gpio"],
                defaults={"peripheral_type": p["peripheral_type"]},
            )
            registered.append(obj)

        return Response({
            "device_id": device_id,
            "registered_count": len(registered),
            "peripherals": PeripheralSerializer(registered, many=True).data,
        }, status=status.HTTP_200_OK)


class ListPeripheralsView(APIView):
    """GET /api/nodes/peripherals/?device_id=2137 — lista peryferiów (wymaga JWT użytkownika z dostępem)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        device_id = request.query_params.get("device_id")
        if not device_id:
            return Response({"detail": "Query parameter 'device_id' is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            gateway = CentralUnit.objects.get(device_id=device_id)
        except CentralUnit.DoesNotExist:
            return Response({"detail": "Device not found."}, status=status.HTTP_404_NOT_FOUND)

        if not DeviceOwnership.objects.filter(user=request.user, device=gateway).exists():
            return Response({"detail": "Access denied."}, status=status.HTTP_403_FORBIDDEN)

        peripherals = ControllableNode.objects.filter(gateway=gateway).order_by("node_id", "gpio")
        return Response({
            "device_id": device_id,
            "peripherals": PeripheralSerializer(peripherals, many=True).data,
        })


class SendCommandView(APIView):
    """POST /api/nodes/command/ — użytkownik wysyła komendę do peryferiów.

    Waliduje:
    - czy peripheral (device_id + node_id + gpio) istnieje
    - czy komenda jest ze zbioru legalnych komend dla danego peripheral_type
    - czy parametr czasu jest podany gdy wymagany (i pominięty gdy nie wymagany)
    - czy użytkownik ma dostęp do urządzenia (DeviceOwnership)
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = SendCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        peripheral = serializer.validated_data["_peripheral"]
        gateway = peripheral.gateway

        # Sprawdź dostęp użytkownika do gatewaya
        if not DeviceOwnership.objects.filter(user=request.user, device=gateway).exists():
            return Response({"detail": "Access denied."}, status=status.HTTP_403_FORBIDDEN)

        cmd = QueuedCommand.objects.create(
            peripheral=peripheral,
            issued_by=request.user,
            command=serializer.validated_data["_cmd_name"],
            time=serializer.validated_data["_time"],
        )

        return Response(QueuedCommandSerializer(cmd).data, status=status.HTTP_201_CREATED)


class HeartbeatView(APIView):
    """POST /api/nodes/heartbeat/ — gateway odbiera zakolejkowane komendy.

    Wymaga JWT urządzenia (device_user). Żadnego payloadu — tożsamość gatewaya
    wynika z tokenu JWT. Zwraca wszystkie komendy ze statusem 'pending'
    i atomicznie oznacza je jako 'delivered'.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # JWT musi należeć do device_user, nie do zwykłego użytkownika
        try:
            gateway = CentralUnit.objects.get(device_user=request.user)
        except CentralUnit.DoesNotExist:
            return Response(
                {"detail": "This JWT does not belong to any registered gateway."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Pobierz wszystkie pending komendy dla tego gatewaya
        pending = QueuedCommand.objects.filter(
            peripheral__gateway=gateway,
            status=QueuedCommand.STATUS_PENDING,
        ).select_related("peripheral")

        commands = list(pending)  # Zmaterializuj przed aktualizacją

        # Atomiocznie oznacz jako dostarczone
        now = timezone.now()
        pending.update(status=QueuedCommand.STATUS_DELIVERED, delivered_at=now)

        return Response(
            {
                "device_id": gateway.device_id,
                "pending_count": len(commands),
                "commands": QueuedCommandSerializer(commands, many=True).data,
            },
            status=status.HTTP_200_OK,
        )
