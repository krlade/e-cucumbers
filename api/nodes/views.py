from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import CentralUnit, ControllableNode, DeviceOwnership, PairingToken, QueuedCommand, TelemetryReading
from .serializers import (
    DeviceListSerializer,
    NodeConfigSerializer,
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
    """POST /api/nodes/register-device/ — rejestracja lub ponowna rejestracja gateway.

    Jeśli gateway z tym samym device_id już istnieje i właściciel jest adminem
    → wydaje nowe tokeny JWT dla istniejącego konta urządzenia.
    Stare dane telemetryczne i komendy zostają zachowane (ciągłość).
    """
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
    """POST /api/nodes/register-peripherals/ — gateway rejestruje peryferia (wymaga JWT urządzenia).

    Endpoint zachowany dla kompatybilności wstecznej i symulatora.
    Operacja idempotentna (upsert).
    """
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


class NodeConfigView(APIView):
    """POST /api/nodes/node-config/ — użytkownik konfiguruje węzeł (etykieta, typ czujnika, gpio).

    Umożliwia skonfigurowanie węzła po tym jak dane zaczną napływać.
    Tworzy lub aktualizuje rekord ControllableNode (upsert).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = NodeConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        device_id = serializer.validated_data["device_id"]
        node_id = serializer.validated_data["node_id"]

        try:
            gateway = CentralUnit.objects.get(device_id=device_id)
        except CentralUnit.DoesNotExist:
            return Response({"detail": "Device not found."}, status=status.HTTP_404_NOT_FOUND)

        if not DeviceOwnership.objects.filter(
            user=request.user, device=gateway, role=DeviceOwnership.ROLE_ADMIN
        ).exists():
            return Response({"detail": "Access denied. Admin role required."}, status=status.HTTP_403_FORBIDDEN)

        defaults = {}
        if "label" in serializer.validated_data:
            defaults["label"] = serializer.validated_data["label"]
        if "sensor_type" in serializer.validated_data:
            defaults["sensor_type"] = serializer.validated_data["sensor_type"]
        if "gpio" in serializer.validated_data:
            defaults["gpio"] = serializer.validated_data["gpio"]
        if "peripheral_type" in serializer.validated_data:
            defaults["peripheral_type"] = serializer.validated_data["peripheral_type"]

        node, created = ControllableNode.objects.update_or_create(
            gateway=gateway,
            node_id=node_id,
            defaults=defaults,
        )

        # Aktualizuj sensor_type w historycznych odczytach telemetrii (jeśli podano)
        if "sensor_type" in serializer.validated_data and serializer.validated_data["sensor_type"]:
            TelemetryReading.objects.filter(
                gateway=gateway,
                node_id=node_id,
                sensor_type__isnull=True,
            ).update(sensor_type=serializer.validated_data["sensor_type"])

        return Response(PeripheralSerializer(node).data, status=status.HTTP_200_OK)


class SendCommandView(APIView):
    """POST /api/nodes/command/ — użytkownik wysyła komendę do węzła Pico przez gateway.

    Format KISS: device_id + node_id + gpio + command (+ opcjonalny czas w minutach).
    Nie wymaga pre-rejestracji węzła.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = SendCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        gateway = serializer.validated_data["_gateway"]

        # Sprawdź dostęp użytkownika do gatewaya
        if not DeviceOwnership.objects.filter(user=request.user, device=gateway).exists():
            return Response({"detail": "Access denied."}, status=status.HTTP_403_FORBIDDEN)

        cmd = QueuedCommand.objects.create(
            gateway=gateway,
            node_id=serializer.validated_data["node_id"],
            gpio=serializer.validated_data["gpio"],
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

        commands = QueuedCommand.objects.filter(gateway=gateway).order_by("-created_at")[:limit]
        return Response(QueuedCommandSerializer(commands, many=True).data)


class HeartbeatView(APIView):
    """POST /api/nodes/heartbeat/ — gateway odbiera zakolejkowane komendy.

    Wymaga JWT urządzenia (device_user). Żadnego payloadu — tożsamość gatewaya
    wynika z tokenu JWT. Zwraca wszystkie komendy ze statusem 'pending'
    i atomicznie oznacza je jako 'delivered'.

    Zapisuje czas heartbeatu — używany do statusu Online/Offline.
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

        # Zapisz czas heartbeatu (Online/Offline)
        gateway.last_heartbeat = timezone.now()
        gateway.save(update_fields=["last_heartbeat"])

        # Pobierz wszystkie pending komendy dla tego gatewaya
        pending = QueuedCommand.objects.filter(
            gateway=gateway,
            status=QueuedCommand.STATUS_PENDING,
        )

        commands = list(pending)  # Zmaterializuj przed aktualizacją

        # Atomicznie oznacz jako dostarczone
        now = timezone.now()
        pending.update(status=QueuedCommand.STATUS_DELIVERED, delivered_at=now)

        # Uproszczony format dla Gateway: TURN_ON / TURN_OFF + node_id + gpio
        gateway_commands = []
        for cmd in commands:
            # Komendy czasowe są zredukowane do prostego TURN_ON — Gateway nie zarządza czasem
            simple_cmd = "TURN_ON" if cmd.command in ["TURN_ON", "TURN_ON_FOR", "WATER_PUMP_ON"] else "TURN_OFF"
            gateway_commands.append({
                "id": cmd.id,
                "node_id": cmd.node_id,
                "gpio": cmd.gpio,
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
    """POST /api/nodes/telemetry/ — gateway przesyła surowy odczyt z węzła Pico.

    Gateway przekazuje payload 1:1 tak jak dostał od węzła.
    Węzeł Pico wysyła: {"data": 23.5}
    Gateway przesyła: {"node_id": "Pico_01", "payload": {"data": 23.5}}

    sensor_type jest pobierany z konfiguracji węzła (ControllableNode), jeśli węzeł
    jest skonfigurowany przez użytkownika. W przeciwnym razie odczyt jest zapisywany
    bez typu czujnika — użytkownik może skonfigurować go później przez /node-config/.

    Nie wymaga pre-rejestracji węzła.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # JWT musi należeć do device_user
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
        raw_payload = serializer.validated_data["payload"]

        # Wyekstrahuj wartość liczbową z payloadu (klucz "data" zgodnie z protokołem Pico)
        value = None
        raw_val = raw_payload.get("data")
        if raw_val is not None:
            try:
                value = float(raw_val)
            except (ValueError, TypeError):
                pass

        # Pobierz sensor_type z konfiguracji węzła (jeśli skonfigurowany przez użytkownika)
        sensor_type = None
        try:
            node_config = ControllableNode.objects.get(gateway=gateway, node_id=node_id)
            sensor_type = node_config.sensor_type
        except ControllableNode.DoesNotExist:
            pass

        reading = TelemetryReading.objects.create(
            gateway=gateway,
            node_id=node_id,
            raw_payload=raw_payload,
            value=value,
            sensor_type=sensor_type,
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
        node_id = request.query_params.get("node_id")
        limit = request.query_params.get("limit", 50)
        try:
            limit = int(limit)
        except ValueError:
            limit = 50

        readings = TelemetryReading.objects.filter(gateway=gateway)
        if sensor_type:
            readings = readings.filter(sensor_type=sensor_type)
        if node_id:
            readings = readings.filter(node_id=node_id)

        readings = readings.order_by("-recorded_at")[:limit]
        # Zwróć w porządku rosnącym (ASC) — gotowe do wykresów
        readings_list = list(readings)[::-1]

        return Response(TelemetryReadingSerializer(readings_list, many=True).data)


class ListDevicesView(APIView):
    """GET /api/nodes/user-devices/ — lista gateway'ów użytkownika z statusem Online/Offline."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        ownerships = DeviceOwnership.objects.filter(user=request.user).select_related("device")
        devices_list = []
        for o in ownerships:
            devices_list.append({
                "device_id": o.device.device_id,
                "role": o.role,
                "registered_at": o.device.registered_at.isoformat(),
                "last_heartbeat": o.device.last_heartbeat.isoformat() if o.device.last_heartbeat else None,
                "is_online": o.device.is_online,
            })
        return Response(devices_list)
