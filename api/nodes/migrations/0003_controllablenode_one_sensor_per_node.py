from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("nodes", "0002_add_controllable_node_and_queued_command"),
    ]

    operations = [
        # Najpierw usuń stary unique_together (gateway, node_id, gpio)
        migrations.AlterUniqueTogether(
            name="controllablenode",
            unique_together=set(),
        ),
        # gpio i peripheral_type stają się opcjonalne
        migrations.AlterField(
            model_name="controllablenode",
            name="gpio",
            field=models.PositiveSmallIntegerField(
                null=True, blank=True, help_text="Numer pinu GPIO (tylko dla węzłów sterowanych)"
            ),
        ),
        migrations.AlterField(
            model_name="controllablenode",
            name="peripheral_type",
            field=models.CharField(
                max_length=16,
                choices=[("LAMP", "Lampa"), ("SPRINKLER", "Zraszacz")],
                null=True,
                blank=True,
            ),
        ),
        # Nowe pole sensor_type
        migrations.AddField(
            model_name="controllablenode",
            name="sensor_type",
            field=models.CharField(
                max_length=16,
                choices=[
                    ("temperature", "Temperatura (°C)"),
                    ("humidity", "Wilgotność (%)"),
                    ("light", "Natężenie światła (lux)"),
                ],
                null=True,
                blank=True,
                help_text="Typ czujnika zamontowanego w węźle (dokładnie 1 czujnik lub brak)",
            ),
        ),
        # Nowy unique_together: (gateway, node_id) — jeden węzeł per gateway
        migrations.AlterUniqueTogether(
            name="controllablenode",
            unique_together={("gateway", "node_id")},
        ),
    ]
