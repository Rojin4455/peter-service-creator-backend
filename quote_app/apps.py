from django.apps import AppConfig


class QuoteAppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'quote_app'

    def ready(self):
        import quote_app.signals  # noqa: F401 - register signals
