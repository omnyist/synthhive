from __future__ import annotations

from django.urls import path

from . import auth_views

urlpatterns = [
    path("<uuid:bot_id>/", auth_views.setup_page, name="setup"),
    path("connect/", auth_views.twitch_connect, name="twitch_connect"),
    path("callback/", auth_views.twitch_callback, name="twitch_callback"),
]
