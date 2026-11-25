from django.urls import path

from . import views

urlpatterns = [
    path("assistant/", views.assistant, name="assistant"),
    path("assistant/panel/", views.panel, name="assistant_panel"),
    path("assistant/clear/", views.clear, name="assistant_clear"),
]
