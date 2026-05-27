from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import CentralUnit, ControllableNode, DeviceOwnership, PairingToken, QueuedCommand, TelemetryReading
from .serializers import (
    PeripheralSerializer,
    PairingTokenResponseSerializer,
    QueuedCommandSerializer,
    RegisterDeviceSerializer,
    RegisterPeripheralsSerializer,
    SendCommandSerializer,
    TelemetrySerializer,
    TelemetryReadingSerializer,
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

        device_username = f"device_{device_id}"
        device_user, created = User.objects.get_or_create(username=device_username)
        if created:
            device_user.set_unusable_password()
            device_user.is_active = True
            device_user.save()
            
        unit = CentralUnit.objects.create(device_id=device_id, device_user=device_user)
        DeviceOwnership.objects.create(user=owner, device=unit, role=DeviceOwnership.ROLE_ADMIN)
        pairing_token.delete()

        refresh = RefreshToken.for_user(device_user)
        return Response({
            "device_id": device_id, "owner": owner.username,
            "access": str(refresh.access_token), "refresh": str(refresh),
        }, status=status.HTTP_200_OK)

    def delete(self, request):
        if not request.user.is_authenticated:
            return Response({"detail": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)

        device_id = request.data.get("device_id") or request.query_params.get("device_id")
        if not device_id:
            return Response({"detail": "Field 'device_id' is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            gateway = CentralUnit.objects.get(device_id=device_id)
        except CentralUnit.DoesNotExist:
            return Response({"detail": "Device not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            ownership = DeviceOwnership.objects.get(user=request.user, device=gateway)
        except DeviceOwnership.DoesNotExist:
            return Response({"detail": "You do not own this device."}, status=status.HTTP_403_FORBIDDEN)

        if ownership.role != DeviceOwnership.ROLE_ADMIN:
            ownership.delete()
            return Response({"detail": "Ownership removed successfully."}, status=status.HTTP_200_OK)

        device_user = gateway.device_user
        device_user.delete()

        return Response({"detail": "Device unregistered and deleted successfully."}, status=status.HTTP_200_OK)



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
                gateway=gateway, node_id=p["node_id"],
                defaults={
                    "gpio": p.get("gpio"),
                    "peripheral_type": p.get("peripheral_type"),
                    "sensor_type": p.get("sensor_type"),
                },
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

    def get(self, request):
        device_id = request.query_params.get("device_id")
        if not device_id:
            return Response({"detail": "Query parameter 'device_id' is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            gateway = CentralUnit.objects.get(device_id=device_id)
        except CentralUnit.DoesNotExist:
            return Response({"detail": "Device not found."}, status=status.HTTP_404_NOT_FOUND)

        is_device_user = (gateway.device_user == request.user)
        is_owner = DeviceOwnership.objects.filter(user=request.user, device=gateway).exists()
        if not (is_device_user or is_owner):
            return Response({"detail": "Access denied."}, status=status.HTTP_403_FORBIDDEN)

        limit = request.query_params.get("limit", 20)
        try:
            limit = int(limit)
        except ValueError:
            limit = 20

        commands = QueuedCommand.objects.filter(peripheral__gateway=gateway).order_by("-created_at")[:limit]
        return Response(QueuedCommandSerializer(commands, many=True).data)


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
        # Map and simplify commands for the gateway (no timers, no peripheral type)
        gateway_commands = []
        for cmd in commands:
            simple_cmd = "TURN_ON" if cmd.command in ["TURN_ON", "TURN_ON_FOR", "WATER_PUMP_ON"] else "TURN_OFF"
            gateway_commands.append({
                "id": cmd.id,
                "node_id": cmd.peripheral.node_id,
                "gpio": cmd.peripheral.gpio,
                "command": simple_cmd,
            })

        return Response(
            {
                "device_id": gateway.device_id,
                "pending_count": len(gateway_commands),
                "commands": gateway_commands,
            },
            status=status.HTTP_200_OK,
        )


class TelemetryView(APIView):
    """POST /api/nodes/telemetry/ — gateway wysyla odczyt z czujnika.

    Wymaga JWT urzadzenia. Kazdy wezel (Pico) ma dokladnie 1 czujnik.
    node_id + JWT (gateway) jednoznacznie identyfikuja zrodlo odczytu.
    Brak pre-rejestracji sensorow — przyjmujemy dane z kazdego node_id.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # JWT musi nalezec do device_user
        try:
            gateway = CentralUnit.objects.get(device_user=request.user)
        except CentralUnit.DoesNotExist:
            return Response(
                {"detail": "This JWT does not belong to any registered gateway."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = TelemetrySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        node_id = serializer.validated_data["node_id"]

        try:
            node = ControllableNode.objects.get(gateway=gateway, node_id=node_id)
        except ControllableNode.DoesNotExist:
            return Response(
                {"detail": f"Węzeł '{node_id}' nie jest zarejestrowany w tym gateway."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not node.sensor_type:
            return Response(
                {"detail": f"Węzeł '{node_id}' nie ma zarejestrowanego czujnika."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reading = TelemetryReading.objects.create(
            gateway=gateway,
            node_id=node_id,
            sensor_type=node.sensor_type,
            value=serializer.validated_data["value"],
        )

        return Response(
            TelemetryReadingSerializer(reading).data,
            status=status.HTTP_201_CREATED,
        )

    def get(self, request):
        device_id = request.query_params.get("device_id")
        if not device_id:
            return Response({"detail": "Query parameter 'device_id' is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            gateway = CentralUnit.objects.get(device_id=device_id)
        except CentralUnit.DoesNotExist:
            return Response({"detail": "Device not found."}, status=status.HTTP_404_NOT_FOUND)

        is_device_user = (gateway.device_user == request.user)
        is_owner = DeviceOwnership.objects.filter(user=request.user, device=gateway).exists()
        if not (is_device_user or is_owner):
            return Response({"detail": "Access denied."}, status=status.HTTP_403_FORBIDDEN)

        sensor_type = request.query_params.get("sensor_type")
        limit = request.query_params.get("limit", 50)
        try:
            limit = int(limit)
        except ValueError:
            limit = 50

        readings = TelemetryReading.objects.filter(gateway=gateway)
        if sensor_type:
            readings = readings.filter(sensor_type=sensor_type)

        readings = readings.order_by("-recorded_at")[:limit]
        # Return in ascending order of recorded_at for easier charting
        readings_list = list(readings)[::-1]

        return Response(TelemetryReadingSerializer(readings_list, many=True).data)


class ListDevicesView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        ownerships = DeviceOwnership.objects.filter(user=request.user).select_related("device")
        devices_list = []
        for o in ownerships:
            devices_list.append({
                "device_id": o.device.device_id,
                "role": o.role,
                "registered_at": o.device.registered_at.isoformat()
            })
        return Response(devices_list)

