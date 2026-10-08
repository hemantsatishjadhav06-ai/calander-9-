from django.urls import path

from . import views

app_name = "studio"

urlpatterns = [
    path("", views.index, name="index"),
    path("new/", views.create, name="create"),
    path("brand/", views.brand_profile, name="brand"),
    path("brand/sample/<str:template>.jpg", views.brand_sample, name="brand_sample"),
    path("<uuid:brief_id>/", views.detail, name="detail"),
    path("<uuid:brief_id>/progress/", views.progress, name="progress"),
    path("<uuid:brief_id>/approve/", views.approve, name="approve"),
    path("<uuid:brief_id>/changes/", views.request_changes, name="request_changes"),
    path("<uuid:brief_id>/angles/", views.new_angles, name="new_angles"),
    path("<uuid:brief_id>/angles/<uuid:concept_id>/use/", views.use_angle, name="use_angle"),
    path("<uuid:brief_id>/angles/<uuid:concept_id>/save/", views.save_idea, name="save_idea"),
    path("<uuid:brief_id>/retry/", views.retry, name="retry"),
    path("<uuid:brief_id>/discard/", views.discard, name="discard"),
]
