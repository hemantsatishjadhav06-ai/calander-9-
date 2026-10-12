from django.urls import path

from . import views_outcomes

urlpatterns = [path("outcomes/", views_outcomes.outcome_page, name="outcomes")]
