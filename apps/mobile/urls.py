"""Phone screens, under /workspace/<id>/app/."""

from django.urls import path

from . import views

app_name = "mobile"

urlpatterns = [
    path("today/", views.today, name="today"),
    path("more/", views.more, name="more"),
    path("post/<uuid:post_id>/", views.post_detail, name="post"),
]
