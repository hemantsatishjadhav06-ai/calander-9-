from django.urls import path

from . import views_trust

urlpatterns = [path("verified-facts/", views_trust.verified_facts, name="trust")]
