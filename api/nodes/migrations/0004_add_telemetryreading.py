import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("nodes", "0003_controllablenode_one_sensor_per_node"),
    ]

    operations = [
        migrations.CreateModel(
            name="TelemetryReading",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("node_id", models.CharField(help_text="ID węzła, np. 'Pico_01'", max_length=64)),
                (
                    "sensor_type",
                    models.CharField(
                        choices=[
                            ("temperature", "Temperatura (°C)"),
                            ("humidity", "Wilgotność (%)"),
                            ("light", "Natężenie światła (lux)"),
                        ],
                        max_length=16,
                    ),
                ),
                ("value", models.FloatField()),
                ("recorded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "gateway",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="telemetry_readings",
                        to="nodes.centralunit",
                    ),
                ),
            ],
            options={
                "ordering": ["-recorded_at"],
                "indexes": [
                    models.Index(fields=["gateway", "node_id", "-recorded_at"], name="nodes_telemetr_gateway_idx"),
                ],
            },
        ),
    ]
