from django.apps import AppConfig

class EcucumbersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ecucumbers"

    def ready(self):
        from . import mqtt_client
        mqtt_client.init_mqtt()
