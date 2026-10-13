from django.urls import path

from . import views_delivery

app_name = "publisher_delivery"

urlpatterns = [
    path("reconcile/<uuid:platform_post_id>/", views_delivery.reconcile_existing, name="reconcile_existing"),
    path("checked-absent/<uuid:platform_post_id>/", views_delivery.checked_absent, name="checked_absent"),
]
