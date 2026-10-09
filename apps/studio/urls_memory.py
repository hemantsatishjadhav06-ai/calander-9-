"""URLs for the agency's memory pages (see views_memory.py). Included by apps/studio/urls.py."""

from django.urls import path

from . import views_memory

urlpatterns = [
    path("memory/", views_memory.memory, name="memory"),
    path("memory/house-style/", views_memory.house_style, name="memory_house_style"),
    path("memory/references/", views_memory.upload_references, name="memory_upload"),
    path("memory/refresh/", views_memory.refresh, name="memory_refresh"),
    path("memory/<uuid:insight_id>/reference/", views_memory.toggle_reference, name="memory_reference"),
]
