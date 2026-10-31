from django.urls import path

from . import views_settings

# The Settings screen, mounted at /workspace/<id>/settings/ (config/urls.py), ahead of the
# client admin under /settings/clients/. Tabs are ?tab=<key>, never a path part.
app_name = "settings"

urlpatterns = [
    path("", views_settings.index, name="index"),
]
