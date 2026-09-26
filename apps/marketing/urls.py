from django.urls import path

from . import views

app_name = "marketing"

urlpatterns = [
    path("", views.home, name="home"),
    path("features/", views.features, name="features"),
    path("how-it-works/", views.how_it_works, name="how_it_works"),
    path("platforms/", views.platforms, name="platforms"),
    path("developers/", views.developers, name="developers"),
    path("get-started/", views.get_started, name="get_started"),
]
