from __future__ import annotations

import logging
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from core.synthfunc import _get
from core.synthfunc import _post
from core.twitch import twitch_request


def _mock_httpx_response(status_code=200, json_data=None, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    response.text = text
    return response


def _make_mock_channel(channel_name="testchannel"):
    channel = MagicMock()
    channel.owner_access_token = "fake_token"
    channel.twitch_channel_id = "12345"
    channel.twitch_channel_name = channel_name
    return channel


def _mock_client(side_effect=None, return_value=None):
    client = AsyncMock()
    if side_effect:
        client.request.side_effect = side_effect
        client.get.side_effect = side_effect
        client.post.side_effect = side_effect
    elif return_value:
        client.request.return_value = return_value
        client.get.return_value = return_value
        client.post.return_value = return_value
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.fixture(autouse=True)
def _clear_network_state():
    """Reset module-level network state between tests."""
    import core.synthfunc
    import core.twitch

    core.twitch._network_errors.clear()
    core.synthfunc._synthfunc_down = False

    # Enable propagation so caplog can capture bot logger output
    bot_logger = logging.getLogger("bot")
    orig_propagate = bot_logger.propagate
    bot_logger.propagate = True

    yield

    bot_logger.propagate = orig_propagate
    core.twitch._network_errors.clear()
    core.synthfunc._synthfunc_down = False


class TestTwitchRequestNetworkErrors:
    async def test_connect_error_logs_once(self, caplog):
        channel = _make_mock_channel()
        client = _mock_client(side_effect=httpx.ConnectError("DNS failed"))

        with (
            patch("core.twitch.httpx.AsyncClient", return_value=client),
            patch(
                "core.synthfunc.get_token",
                new_callable=AsyncMock,
                return_value={"access_token": "token"},
            ),
            caplog.at_level(logging.WARNING, logger="bot"),
        ):
            result1 = await twitch_request(
                channel, "GET", "https://api.twitch.tv/helix/streams"
            )
            result2 = await twitch_request(
                channel, "GET", "https://api.twitch.tv/helix/streams"
            )

        assert result1 is None
        assert result2 is None

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "unreachable" in warnings[0].message
        assert "#testchannel" in warnings[0].message

    async def test_timeout_error_logs_once(self, caplog):
        channel = _make_mock_channel()
        client = _mock_client(side_effect=httpx.TimeoutException("timed out"))

        with (
            patch("core.twitch.httpx.AsyncClient", return_value=client),
            patch(
                "core.synthfunc.get_token",
                new_callable=AsyncMock,
                return_value={"access_token": "token"},
            ),
            caplog.at_level(logging.WARNING, logger="bot"),
        ):
            await twitch_request(
                channel, "GET", "https://api.twitch.tv/helix/streams"
            )
            await twitch_request(
                channel, "GET", "https://api.twitch.tv/helix/streams"
            )

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "TimeoutException" in warnings[0].message

    async def test_recovery_logging(self, caplog):
        channel = _make_mock_channel()
        error_client = _mock_client(
            side_effect=httpx.ConnectError("DNS failed")
        )
        ok_response = _mock_httpx_response()
        ok_client = _mock_client(return_value=ok_response)

        with (
            patch(
                "core.twitch.httpx.AsyncClient",
                side_effect=[error_client, ok_client],
            ),
            patch(
                "core.synthfunc.get_token",
                new_callable=AsyncMock,
                return_value={"access_token": "token"},
            ),
            caplog.at_level(logging.INFO, logger="bot"),
        ):
            await twitch_request(
                channel, "GET", "https://api.twitch.tv/helix/streams"
            )
            await twitch_request(
                channel, "GET", "https://api.twitch.tv/helix/streams"
            )

        info_msgs = [
            r for r in caplog.records
            if r.levelno == logging.INFO and "recovered" in r.message.lower()
        ]
        assert len(info_msgs) == 1
        assert "#testchannel" in info_msgs[0].message

    async def test_per_channel_tracking(self, caplog):
        channel_a = _make_mock_channel(channel_name="channelA")
        channel_b = _make_mock_channel(channel_name="channelB")
        client = _mock_client(side_effect=httpx.ConnectError("DNS failed"))

        with (
            patch("core.twitch.httpx.AsyncClient", return_value=client),
            patch(
                "core.synthfunc.get_token",
                new_callable=AsyncMock,
                return_value={"access_token": "token"},
            ),
            caplog.at_level(logging.WARNING, logger="bot"),
        ):
            await twitch_request(
                channel_a, "GET", "https://api.twitch.tv/helix/streams"
            )
            await twitch_request(
                channel_b, "GET", "https://api.twitch.tv/helix/streams"
            )

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 2
        assert "#channelA" in warnings[0].message
        assert "#channelB" in warnings[1].message

    async def test_non_network_error_always_logs(self, caplog):
        channel = _make_mock_channel()
        client = _mock_client(
            side_effect=httpx.HTTPStatusError(
                "500", request=MagicMock(), response=MagicMock()
            )
        )

        with (
            patch("core.twitch.httpx.AsyncClient", return_value=client),
            patch(
                "core.synthfunc.get_token",
                new_callable=AsyncMock,
                return_value={"access_token": "token"},
            ),
            caplog.at_level(logging.ERROR, logger="bot"),
        ):
            await twitch_request(
                channel, "GET", "https://api.twitch.tv/helix/streams"
            )
            await twitch_request(
                channel, "GET", "https://api.twitch.tv/helix/streams"
            )

        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 2


class TestSynthfuncNetworkErrors:
    async def test_get_connect_error_logs_once(self, caplog):
        client = _mock_client(side_effect=httpx.ConnectError("DNS failed"))

        with (
            patch("core.synthfunc.httpx.AsyncClient", return_value=client),
            patch("core.synthfunc.settings") as mock_settings,
            caplog.at_level(logging.WARNING, logger="bot"),
        ):
            mock_settings.SYNTHFUNC_API_URL = "http://localhost:8000/api"
            mock_settings.SYNTHFUNC_API_KEY = "testkey"

            result1 = await _get("/test", tenant_slug="test")
            result2 = await _get("/test", tenant_slug="test")

        assert result1 is None
        assert result2 is None

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "unreachable" in warnings[0].message.lower()

    async def test_get_recovery_logging(self, caplog):
        error_client = _mock_client(
            side_effect=httpx.ConnectError("DNS failed")
        )
        ok_response = _mock_httpx_response(json_data={"ok": True})
        ok_client = _mock_client(return_value=ok_response)

        with (
            patch(
                "core.synthfunc.httpx.AsyncClient",
                side_effect=[error_client, ok_client],
            ),
            patch("core.synthfunc.settings") as mock_settings,
            caplog.at_level(logging.INFO, logger="bot"),
        ):
            mock_settings.SYNTHFUNC_API_URL = "http://localhost:8000/api"
            mock_settings.SYNTHFUNC_API_KEY = "testkey"

            await _get("/test", tenant_slug="test")
            await _get("/test", tenant_slug="test")

        info_msgs = [
            r for r in caplog.records
            if r.levelno == logging.INFO and "recovered" in r.message.lower()
        ]
        assert len(info_msgs) == 1

    async def test_post_connect_error_logs_once(self, caplog):
        client = _mock_client(side_effect=httpx.ConnectError("DNS failed"))

        with (
            patch("core.synthfunc.httpx.AsyncClient", return_value=client),
            patch("core.synthfunc.settings") as mock_settings,
            caplog.at_level(logging.WARNING, logger="bot"),
        ):
            mock_settings.SYNTHFUNC_API_URL = "http://localhost:8000/api"
            mock_settings.SYNTHFUNC_API_KEY = "testkey"

            result1 = await _post("/test", {"key": "val"}, tenant_slug="test")
            result2 = await _post("/test", {"key": "val"}, tenant_slug="test")

        assert result1 is None
        assert result2 is None

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1

    async def test_post_non_network_error_always_logs(self, caplog):
        client = _mock_client(
            side_effect=httpx.HTTPStatusError(
                "500", request=MagicMock(), response=MagicMock()
            )
        )

        with (
            patch("core.synthfunc.httpx.AsyncClient", return_value=client),
            patch("core.synthfunc.settings") as mock_settings,
            caplog.at_level(logging.ERROR, logger="bot"),
        ):
            mock_settings.SYNTHFUNC_API_URL = "http://localhost:8000/api"
            mock_settings.SYNTHFUNC_API_KEY = "testkey"

            await _post("/test", {"key": "val"}, tenant_slug="test")
            await _post("/test", {"key": "val"}, tenant_slug="test")

        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert len(errors) == 2
