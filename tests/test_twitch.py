from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from core.twitch import twitch_request


def _mock_httpx_response(status_code=200, json_data=None, text=""):
    """Create a mock httpx response."""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    response.text = text
    return response


def _make_mock_channel(
    access_token="fake_token",
    twitch_channel_id="12345",
    channel_name="testchannel",
):
    """Create a mock Channel object."""
    channel = MagicMock()
    channel.owner_access_token = access_token
    channel.twitch_channel_id = twitch_channel_id
    channel.twitch_channel_name = channel_name
    return channel


class TestTwitchRequest:
    async def test_successful_request_uses_synthfunc_token(self):
        channel = _make_mock_channel()

        api_response = _mock_httpx_response(
            json_data={"data": [{"id": "123"}]}
        )

        mock_client = AsyncMock()
        mock_client.request.return_value = api_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("core.twitch.httpx.AsyncClient", return_value=mock_client),
            patch(
                "core.synthfunc.get_token",
                new_callable=AsyncMock,
                return_value={"access_token": "synthfunc_token"},
            ),
        ):
            result = await twitch_request(
                channel,
                "GET",
                "https://api.twitch.tv/helix/channels/followers",
                params={"broadcaster_id": "99999"},
            )

        assert result is not None
        assert result.status_code == 200
        call_kwargs = mock_client.request.call_args
        headers = call_kwargs[1]["headers"]
        assert headers["Authorization"] == "Bearer synthfunc_token"

    async def test_falls_back_to_local_token_when_synthfunc_unreachable(self):
        channel = _make_mock_channel(access_token="local_cached_token")

        api_response = _mock_httpx_response()

        mock_client = AsyncMock()
        mock_client.request.return_value = api_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("core.twitch.httpx.AsyncClient", return_value=mock_client),
            patch(
                "core.synthfunc.get_token",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await twitch_request(
                channel,
                "GET",
                "https://api.twitch.tv/helix/test",
            )

        assert result is not None
        call_kwargs = mock_client.request.call_args
        headers = call_kwargs[1]["headers"]
        assert headers["Authorization"] == "Bearer local_cached_token"

    async def test_no_token_anywhere_returns_none(self):
        channel = _make_mock_channel(access_token="")

        with patch(
            "core.synthfunc.get_token",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await twitch_request(
                channel,
                "GET",
                "https://api.twitch.tv/helix/test",
            )

        assert result is None

    async def test_401_retries_with_fresh_synthfunc_token(self):
        channel = _make_mock_channel()

        unauthorized_response = _mock_httpx_response(status_code=401)
        success_response = _mock_httpx_response(
            json_data={"data": [{"id": "123"}]}
        )

        mock_client = AsyncMock()
        mock_client.request.side_effect = [
            unauthorized_response,
            success_response,
        ]
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_get_token = AsyncMock(
            side_effect=[
                {"access_token": "stale_token"},
                {"access_token": "fresh_token"},
            ]
        )

        with (
            patch("core.twitch.httpx.AsyncClient", return_value=mock_client),
            patch("core.synthfunc.get_token", mock_get_token),
        ):
            result = await twitch_request(
                channel,
                "GET",
                "https://api.twitch.tv/helix/channels/followers",
            )

        assert result is not None
        assert result.status_code == 200
        assert mock_client.request.call_count == 2
        assert mock_get_token.call_count == 2

    async def test_401_with_same_stale_token_returns_none(self):
        channel = _make_mock_channel()

        unauthorized_response = _mock_httpx_response(status_code=401)

        mock_client = AsyncMock()
        mock_client.request.return_value = unauthorized_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_get_token = AsyncMock(
            return_value={"access_token": "same_stale_token"}
        )

        with (
            patch("core.twitch.httpx.AsyncClient", return_value=mock_client),
            patch("core.synthfunc.get_token", mock_get_token),
        ):
            result = await twitch_request(
                channel,
                "GET",
                "https://api.twitch.tv/helix/channels/followers",
            )

        assert result is None

    async def test_401_with_synthfunc_unreachable_on_retry_returns_none(self):
        channel = _make_mock_channel()

        unauthorized_response = _mock_httpx_response(status_code=401)

        mock_client = AsyncMock()
        mock_client.request.return_value = unauthorized_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_get_token = AsyncMock(
            side_effect=[
                {"access_token": "stale_token"},
                None,
            ]
        )

        with (
            patch("core.twitch.httpx.AsyncClient", return_value=mock_client),
            patch("core.synthfunc.get_token", mock_get_token),
        ):
            result = await twitch_request(
                channel,
                "GET",
                "https://api.twitch.tv/helix/channels/followers",
            )

        assert result is None

    async def test_adds_auth_headers(self):
        channel = _make_mock_channel()

        api_response = _mock_httpx_response()

        mock_client = AsyncMock()
        mock_client.request.return_value = api_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("core.twitch.httpx.AsyncClient", return_value=mock_client),
            patch(
                "core.synthfunc.get_token",
                new_callable=AsyncMock,
                return_value={"access_token": "my_bearer_token"},
            ),
            patch("core.twitch.settings") as mock_settings,
        ):
            mock_settings.TWITCH_CLIENT_ID = "test_client_id"
            await twitch_request(
                channel, "GET", "https://api.twitch.tv/helix/test"
            )

        call_kwargs = mock_client.request.call_args
        headers = call_kwargs[1]["headers"]
        assert headers["Authorization"] == "Bearer my_bearer_token"
        assert headers["Client-Id"] == "test_client_id"
