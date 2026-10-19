from django.urls import path

from . import views_setup

# The Set up checklist and the Settings hub, under /workspace/<id>/studio/.
urlpatterns = [
    path("setup/", views_setup.setup, name="setup"),
    path("setup/lead/", views_setup.use_me_as_lead, name="setup_lead"),
    path("setup/autopilot/", views_setup.autopilot_defaults, name="setup_autopilot"),
    path("settings/", views_setup.settings_hub, name="settings_hub"),
]
