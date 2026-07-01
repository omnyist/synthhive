from __future__ import annotations

from django.urls import path

from . import invite_views

urlpatterns = [
    path("<str:code>/", invite_views.invite_landing, name="invite_landing"),
    path(
        "<str:code>/connect-bot/",
        invite_views.invite_connect_bot,
        name="invite_connect_bot",
    ),
]
