from django.apps import AppConfig

class EcucumbersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ecucumbers"

    def ready(self):
        from . import mqtt_client
        mqtt_client.init_mqtt()

        from nodes import scheduler
        scheduler.init_scheduler()

        from . import api_client
        api_client.init_api_client()

        import atexit
        atexit.register(scheduler.shutdown_scheduler)
        atexit.register(api_client.shutdown_api_client)
