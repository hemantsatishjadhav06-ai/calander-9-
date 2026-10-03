from django.apps import AppConfig


class MobileConfig(AppConfig):
    """The phone layout (app bar, bottom tabs, Today and More) and the installable web app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.mobile"
    verbose_name = "Mobile app"
