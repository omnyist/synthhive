"""Tests for the campaign SSE stream."""

from __future__ import annotations

import json

import pytest
from django.contrib.auth.models import User
from django.test import Client

from core.models import TwitchProfile

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture()
def owner_client(channel):
    user = User.objects.create_user(username="owner", password="pass")
    TwitchProfile.objects.create(
        user=user,
        twitch_id=channel.twitch_channel_id,
        twitch_username="owner",
        twitch_display_name="Owner",
        is_approved=True,
    )
    c = Client()
    c.login(username="owner", password="pass")
    return c


class TestStreamAuth:
    def test_anonymous_401(self, channel):
        response = Client().get(
            f"/api/v1/events/channels/{channel.twitch_channel_name}/stream"
        )
        assert response.status_code == 401

    def test_non_owner_404(self, channel):
        user = User.objects.create_user(username="other", password="pass")
        TwitchProfile.objects.create(
            user=user,
            twitch_id="55555",
            twitch_username="other",
            twitch_display_name="Other",
            is_approved=True,
        )
        c = Client()
        c.login(username="other", password="pass")
        response = c.get(
            f"/api/v1/events/channels/{channel.twitch_channel_name}/stream"
        )
        assert response.status_code == 404

    def test_owner_gets_event_stream(self, owner_client, channel):
        response = owner_client.get(
            f"/api/v1/events/channels/{channel.twitch_channel_name}/stream"
        )
        assert response.status_code == 200
        assert response["Content-Type"] == "text/event-stream"
        assert response["Cache-Control"] == "no-cache"


class TestStreamGenerator:
    async def test_forwards_redis_events_as_sse(self):
        from unittest.mock import patch

        import fakeredis.aioredis

        fake = fakeredis.aioredis.FakeRedis()

        with patch(
            "core.event_stream.aioredis.from_url", return_value=fake
        ):
            from core.event_stream import _event_generator

            gen = _event_generator("testchannel")
            first = await gen.__anext__()
            assert first == ": connected\n\n"

            await fake.publish(
                "events:testchannel:campaign",
                json.dumps({"event_type": "campaign:bidwar", "payload": {}}),
            )
            # get_message returns None once while swallowing the subscribe
            # confirmation, which yields a heartbeat — read past pings.
            chunk = ""
            for _ in range(3):
                chunk = await gen.__anext__()
                if chunk.startswith("data: "):
                    break
            assert chunk.startswith("data: ")
            assert "campaign:bidwar" in chunk
            await gen.aclose()
