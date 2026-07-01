from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from core.models import Bot
from core.models import Channel
from core.models import Invite
from core.models import TwitchProfile


@pytest.fixture()
def client(db):
    return Client()


@pytest.fixture()
def test_bot(db):
    return Bot.objects.create(
        name="TestBot",
        twitch_user_id="66977097",
        twitch_username="testbot",
    )


@pytest.fixture()
def test_channel(test_bot):
    return Channel.objects.create(
        bot=test_bot,
        twitch_channel_id="38981465",
        twitch_channel_name="avalonstar",
        is_active=True,
    )


@pytest.fixture()
def approved_user(db):
    user = User.objects.create_user(username="avalonstar")
    profile = TwitchProfile.objects.create(
        user=user,
        twitch_id="38981465",
        twitch_username="avalonstar",
        twitch_display_name="Avalonstar",
        twitch_avatar="",
        is_approved=True,
    )
    return user, profile


TWITCH_USER_DATA = {
    "data": [
        {
            "id": "38981465",
            "login": "avalonstar",
            "display_name": "Avalonstar",
            "profile_image_url": "https://example.com/avatar.png",
        }
    ]
}


def _build_state(nonce: str) -> str:
    from base64 import urlsafe_b64encode

    state_data = {"nonce": nonce, "purpose": "dashboard"}
    return urlsafe_b64encode(json.dumps(state_data).encode()).decode()


def _mock_httpx(token_data=None, user_data=None):
    """Return a patched httpx.AsyncClient context manager."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    token_response = MagicMock()
    token_response.status_code = 200
    token_response.json.return_value = token_data or {
        "access_token": "test-token",
        "refresh_token": "test-refresh",
        "expires_in": 3600,
    }

    user_response = MagicMock()
    user_response.status_code = 200
    user_response.json.return_value = user_data or TWITCH_USER_DATA

    mock_client.post.return_value = token_response
    mock_client.get.return_value = user_response

    return mock_client


class TestTwitchLogin:
    def test_redirects_to_twitch(self, client):
        response = client.get("/auth/twitch/login/")
        assert response.status_code == 302
        assert "id.twitch.tv/oauth2/authorize" in response.url

    def test_requests_channel_scopes(self, client):
        response = client.get("/auth/twitch/login/")
        assert "moderator%3Amanage%3Abanned_users" in response.url
        assert "channel%3Aread%3Asubscriptions" in response.url

    def test_state_contains_nonce(self, client):
        response = client.get("/auth/twitch/login/")
        assert "state=" in response.url

    def test_stores_nonce_in_session(self, client):
        client.get("/auth/twitch/login/")
        session = client.session
        assert "dashboard_oauth_nonce" in session


class TestTwitchCallback:
    @patch("core.dashboard_auth.httpx.AsyncClient")
    def test_approved_user_can_login(self, mock_client_cls, client, approved_user):
        nonce = "test-nonce-123"
        session = client.session
        session["dashboard_oauth_nonce"] = nonce
        session.save()

        mock_client_cls.return_value = _mock_httpx()

        state = _build_state(nonce)
        response = client.get(
            f"/auth/twitch/callback/?code=test-code&state={state}"
        )

        assert response.status_code == 302
        assert response.url == "/"

    @patch("core.dashboard_auth.httpx.AsyncClient")
    def test_updates_profile_on_repeat_login(
        self, mock_client_cls, client, approved_user
    ):
        _, profile = approved_user
        profile.twitch_display_name = "OldName"
        profile.save(update_fields=["twitch_display_name"])

        nonce = "test-nonce-456"
        session = client.session
        session["dashboard_oauth_nonce"] = nonce
        session.save()

        mock_client_cls.return_value = _mock_httpx()

        state = _build_state(nonce)
        response = client.get(
            f"/auth/twitch/callback/?code=test-code&state={state}"
        )

        assert response.status_code == 302
        profile.refresh_from_db()
        assert profile.twitch_display_name == "Avalonstar"
        assert profile.twitch_avatar == "https://example.com/avatar.png"

    @patch("core.dashboard_auth.httpx.AsyncClient")
    def test_denies_unapproved_user(self, mock_client_cls, client):
        nonce = "test-nonce-789"
        session = client.session
        session["dashboard_oauth_nonce"] = nonce
        session.save()

        mock_client_cls.return_value = _mock_httpx(
            user_data={
                "data": [
                    {
                        "id": "99999999",
                        "login": "randomuser",
                        "display_name": "RandomUser",
                        "profile_image_url": "",
                    }
                ]
            },
        )

        state = _build_state(nonce)
        response = client.get(
            f"/auth/twitch/callback/?code=test-code&state={state}"
        )

        assert response.status_code == 400
        assert TwitchProfile.objects.filter(
            twitch_id="99999999", is_approved=False
        ).exists()

    @patch("core.dashboard_auth.httpx.AsyncClient")
    def test_denies_first_login_without_invite(self, mock_client_cls, client):
        nonce = "test-nonce-first"
        session = client.session
        session["dashboard_oauth_nonce"] = nonce
        session.save()

        mock_client_cls.return_value = _mock_httpx()

        state = _build_state(nonce)
        response = client.get(
            f"/auth/twitch/callback/?code=test-code&state={state}"
        )

        assert response.status_code == 400
        assert User.objects.filter(username="avalonstar").exists()
        assert TwitchProfile.objects.filter(
            twitch_id="38981465", is_approved=False
        ).exists()

    @patch("core.dashboard_auth.httpx.AsyncClient")
    def test_superuser_can_login_without_approval(self, mock_client_cls, client):
        """Superusers bypass the approval gate — the bootstrap escape hatch."""
        User.objects.create_superuser(username="avalonstar", password="x")

        nonce = "test-nonce-super"
        session = client.session
        session["dashboard_oauth_nonce"] = nonce
        session.save()

        mock_client_cls.return_value = _mock_httpx()

        state = _build_state(nonce)
        response = client.get(
            f"/auth/twitch/callback/?code=test-code&state={state}"
        )

        assert response.status_code == 302
        assert response.url == "/"

    def test_rejects_missing_code(self, client):
        response = client.get("/auth/twitch/callback/?state=abc")
        assert response.status_code == 400

    def test_rejects_invalid_state(self, client):
        response = client.get(
            "/auth/twitch/callback/?code=test&state=invalid"
        )
        assert response.status_code == 400

    def test_rejects_mismatched_nonce(self, client):
        session = client.session
        session["dashboard_oauth_nonce"] = "correct-nonce"
        session.save()

        state = _build_state("wrong-nonce")
        response = client.get(
            f"/auth/twitch/callback/?code=test&state={state}"
        )
        assert response.status_code == 400

    def test_reports_oauth_error(self, client):
        response = client.get(
            "/auth/twitch/callback/?error=access_denied"
            "&error_description=User+denied"
        )
        assert response.status_code == 400


class TestChannelTokenStorage:
    @patch("core.dashboard_auth._update_channel_tokens")
    @patch("core.dashboard_auth.httpx.AsyncClient")
    def test_login_calls_update_channel_tokens(
        self, mock_client_cls, mock_update, client, approved_user
    ):
        mock_update.return_value = None

        nonce = "test-nonce-tokens"
        session = client.session
        session["dashboard_oauth_nonce"] = nonce
        session.save()

        mock_client_cls.return_value = _mock_httpx()

        state = _build_state(nonce)
        response = client.get(
            f"/auth/twitch/callback/?code=test-code&state={state}"
        )

        assert response.status_code == 302
        mock_update.assert_called_once_with(
            twitch_id="38981465",
            access_token="test-token",
            refresh_token="test-refresh",
            expires_in=3600,
        )

    @patch("core.synthfunc.save_token", new_callable=AsyncMock)
    @patch("core.dashboard_auth.httpx.AsyncClient")
    def test_stores_tokens_on_channel(
        self, mock_client_cls, mock_synthfunc, client, approved_user, test_channel
    ):
        mock_synthfunc.return_value = {"status": "ok"}

        nonce = "test-nonce-channel"
        session = client.session
        session["dashboard_oauth_nonce"] = nonce
        session.save()

        mock_client_cls.return_value = _mock_httpx()

        state = _build_state(nonce)
        response = client.get(
            f"/auth/twitch/callback/?code=test-code&state={state}"
        )

        assert response.status_code == 302
        test_channel.refresh_from_db()
        assert test_channel.owner_access_token == "test-token"
        assert test_channel.owner_refresh_token == "test-refresh"
        assert test_channel.owner_token_expires_at is not None

    @patch("core.synthfunc.save_token", new_callable=AsyncMock)
    @patch("core.dashboard_auth.httpx.AsyncClient")
    def test_pushes_tokens_to_synthfunc(
        self, mock_client_cls, mock_synthfunc, client, approved_user, test_channel
    ):
        mock_synthfunc.return_value = {"status": "ok"}

        nonce = "test-nonce-synth"
        session = client.session
        session["dashboard_oauth_nonce"] = nonce
        session.save()

        mock_client_cls.return_value = _mock_httpx()

        state = _build_state(nonce)
        client.get(f"/auth/twitch/callback/?code=test-code&state={state}")

        mock_synthfunc.assert_called_once_with(
            user_id="38981465",
            access_token="test-token",
            refresh_token="test-refresh",
            expires_in=3600,
        )

    @patch("core.synthfunc.save_token", new_callable=AsyncMock)
    @patch("core.dashboard_auth.httpx.AsyncClient")
    def test_updates_all_channels_for_owner(
        self, mock_client_cls, mock_synthfunc, client, approved_user, test_bot
    ):
        mock_synthfunc.return_value = {"status": "ok"}

        bot2 = Bot.objects.create(
            name="TestBot2",
            twitch_user_id="149214941",
            twitch_username="testbot2",
        )
        ch1 = Channel.objects.create(
            bot=test_bot,
            twitch_channel_id="38981465",
            twitch_channel_name="avalonstar",
            is_active=True,
        )
        ch2 = Channel.objects.create(
            bot=bot2,
            twitch_channel_id="38981465",
            twitch_channel_name="avalonstar",
            is_active=True,
        )
        bot3 = Bot.objects.create(
            name="TestBot3",
            twitch_user_id="99999999",
            twitch_username="testbot3",
        )
        Channel.objects.create(
            bot=bot3,
            twitch_channel_id="38981465",
            twitch_channel_name="avalonstar",
            is_active=False,
        )

        nonce = "test-nonce-multi"
        session = client.session
        session["dashboard_oauth_nonce"] = nonce
        session.save()

        mock_client_cls.return_value = _mock_httpx()

        state = _build_state(nonce)
        client.get(f"/auth/twitch/callback/?code=test-code&state={state}")

        ch1.refresh_from_db()
        ch2.refresh_from_db()
        assert ch1.owner_access_token == "test-token"
        assert ch2.owner_access_token == "test-token"

        inactive = Channel.objects.get(bot=bot3, is_active=False)
        assert inactive.owner_access_token is None

        mock_synthfunc.assert_called_once()

    @patch("core.dashboard_auth.httpx.AsyncClient")
    def test_login_succeeds_without_channels(
        self, mock_client_cls, client, approved_user
    ):
        nonce = "test-nonce-nochan"
        session = client.session
        session["dashboard_oauth_nonce"] = nonce
        session.save()

        mock_client_cls.return_value = _mock_httpx()

        state = _build_state(nonce)
        response = client.get(
            f"/auth/twitch/callback/?code=test-code&state={state}"
        )

        assert response.status_code == 302
        assert response.url == "/"

    @patch("core.synthfunc.save_token", new_callable=AsyncMock)
    @patch("core.dashboard_auth.httpx.AsyncClient")
    def test_synthfunc_failure_does_not_block_login(
        self, mock_client_cls, mock_synthfunc, client, approved_user, test_channel
    ):
        mock_synthfunc.side_effect = Exception("Synthfunc down")

        nonce = "test-nonce-fail"
        session = client.session
        session["dashboard_oauth_nonce"] = nonce
        session.save()

        mock_client_cls.return_value = _mock_httpx()

        state = _build_state(nonce)
        response = client.get(
            f"/auth/twitch/callback/?code=test-code&state={state}"
        )

        assert response.status_code == 302
        assert response.url == "/"
        test_channel.refresh_from_db()
        assert test_channel.owner_access_token == "test-token"


class TestDashboardLogout:
    def test_logout_redirects(self, client):
        User.objects.create_user(username="testuser", password="pass")
        client.login(username="testuser", password="pass")

        response = client.get("/auth/logout/")
        assert response.status_code == 302
        assert response.url == "/"


INVITEE_TWITCH_DATA = {
    "data": [
        {
            "id": "78238052",
            "login": "spoonee",
            "display_name": "Spoonee",
            "profile_image_url": "https://example.com/spoonee.png",
        }
    ]
}

BOT_TWITCH_DATA = {
    "data": [
        {
            "id": "149214941",
            "login": "worldfriendshipbot",
            "display_name": "WorldFriendshipBot",
            "profile_image_url": "",
        }
    ]
}


def _build_invite_state(nonce: str, invite_code: str) -> str:
    from base64 import urlsafe_b64encode

    state_data = {"nonce": nonce, "purpose": "invite", "invite_code": invite_code}
    return urlsafe_b64encode(json.dumps(state_data).encode()).decode()


def _build_invite_bot_state(nonce: str, invite_code: str) -> str:
    from base64 import urlsafe_b64encode

    state_data = {
        "nonce": nonce,
        "purpose": "invite_bot",
        "invite_code": invite_code,
    }
    return urlsafe_b64encode(json.dumps(state_data).encode()).decode()


class TestInviteLanding:
    def test_shows_landing_for_valid_invite(self, client):
        owner = User.objects.create_user(username="owner")
        invite = Invite.objects.create(
            created_by=owner,
            expires_at=timezone.now() + timedelta(days=7),
        )
        response = client.get(f"/invite/{invite.code}/")
        assert response.status_code == 200
        assert b"Welcome to Synthhive" in response.content

    def test_shows_error_for_invalid_code(self, client):
        response = client.get("/invite/badcode/")
        assert response.status_code == 200
        assert b"not valid" in response.content

    def test_shows_error_for_expired_invite(self, client):
        owner = User.objects.create_user(username="owner")
        invite = Invite.objects.create(
            created_by=owner,
            expires_at=timezone.now() - timedelta(hours=1),
        )
        response = client.get(f"/invite/{invite.code}/")
        assert response.status_code == 200
        assert b"expired" in response.content

    def test_shows_error_for_completed_invite(self, client):
        owner = User.objects.create_user(username="owner")
        invitee = User.objects.create_user(username="invitee")
        invite = Invite.objects.create(
            created_by=owner,
            expires_at=timezone.now() + timedelta(days=7),
            used_by=invitee,
            used_at=timezone.now(),
            completed_at=timezone.now(),
        )
        response = client.get(f"/invite/{invite.code}/")
        assert response.status_code == 200
        assert b"already been used" in response.content

    def test_shows_bot_page_for_awaiting_invite(self, client):
        owner = User.objects.create_user(username="owner")
        invitee = User.objects.create_user(username="invitee")
        invite = Invite.objects.create(
            created_by=owner,
            expires_at=timezone.now() + timedelta(days=7),
            used_by=invitee,
            used_at=timezone.now(),
            channel_twitch_id="78238052",
            channel_name="spoonee",
        )
        response = client.get(f"/invite/{invite.code}/")
        assert response.status_code == 200
        assert b"Connect Your Bot" in response.content


class TestInviteChannelOAuth:
    @patch("core.dashboard_auth.httpx.AsyncClient")
    def test_invite_creates_approved_user_and_stores_tokens(
        self, mock_client_cls, client
    ):
        owner = User.objects.create_user(username="owner")
        invite = Invite.objects.create(
            created_by=owner,
            expires_at=timezone.now() + timedelta(days=7),
        )

        nonce = "invite-nonce-1"
        session = client.session
        session["invite_oauth_nonce"] = nonce
        session.save()

        mock_client_cls.return_value = _mock_httpx(user_data=INVITEE_TWITCH_DATA)

        state = _build_invite_state(nonce, invite.code)
        response = client.get(
            f"/auth/twitch/callback/?code=test-code&state={state}"
        )

        assert response.status_code == 302
        assert f"/invite/{invite.code}/connect-bot/" in response.url

        profile = TwitchProfile.objects.get(twitch_id="78238052")
        assert profile.is_approved is True
        assert profile.twitch_display_name == "Spoonee"

        invite.refresh_from_db()
        assert invite.used_at is not None
        assert invite.channel_twitch_id == "78238052"
        assert invite.channel_name == "spoonee"
        assert invite.channel_access_token == "test-token"
        assert invite.completed_at is None

    @patch("core.dashboard_auth.httpx.AsyncClient")
    def test_invite_rejects_expired(self, mock_client_cls, client):
        owner = User.objects.create_user(username="owner")
        invite = Invite.objects.create(
            created_by=owner,
            expires_at=timezone.now() - timedelta(hours=1),
        )

        nonce = "invite-nonce-expired"
        session = client.session
        session["invite_oauth_nonce"] = nonce
        session.save()

        mock_client_cls.return_value = _mock_httpx(user_data=INVITEE_TWITCH_DATA)

        state = _build_invite_state(nonce, invite.code)
        response = client.get(
            f"/auth/twitch/callback/?code=test-code&state={state}"
        )

        assert response.status_code == 400


def _awaiting_bot_invite(nonce="bot-nonce-1", channel_twitch_id="78238052"):
    """Create an invite that has completed step 1 and awaits bot connection."""
    owner = User.objects.create_user(username="owner")
    invitee = User.objects.create_user(username="spoonee")
    return Invite.objects.create(
        created_by=owner,
        expires_at=timezone.now() + timedelta(days=7),
        used_by=invitee,
        used_at=timezone.now(),
        channel_twitch_id=channel_twitch_id,
        channel_name="spoonee",
        channel_access_token="channel-token",
        channel_refresh_token="channel-refresh",
        channel_token_expires_at=timezone.now() + timedelta(hours=1),
        bot_oauth_nonce=nonce,
    )


class TestInviteBotOAuth:
    @patch("core.synthfunc.save_token", new_callable=AsyncMock)
    @patch("core.dashboard_auth.httpx.AsyncClient")
    def test_bot_oauth_works_cross_browser(
        self, mock_client_cls, mock_synthfunc, client
    ):
        """The bot step must succeed with NO session — the invitee finishes
        it in a separate incognito browser. The nonce lives on the invite."""
        mock_synthfunc.return_value = {"status": "ok"}

        invite = _awaiting_bot_invite(nonce="bot-nonce-1")

        # Deliberately do NOT set any session nonce — simulates incognito.
        mock_client_cls.return_value = _mock_httpx(user_data=BOT_TWITCH_DATA)

        state = _build_invite_bot_state("bot-nonce-1", invite.code)
        response = client.get(
            f"/auth/twitch/callback/?code=test-code&state={state}"
        )

        assert response.status_code == 200
        assert b"all set" in response.content

        bot = Bot.objects.get(twitch_user_id="149214941")
        assert bot.name == "WorldFriendshipBot"
        assert bot.access_token == "test-token"

        channel = Channel.objects.get(
            bot=bot, twitch_channel_id="78238052"
        )
        assert channel.twitch_channel_name == "spoonee"
        assert channel.owner_access_token == "channel-token"

        invite.refresh_from_db()
        assert invite.completed_at is not None
        assert invite.channel_access_token is None
        assert invite.bot_oauth_nonce == ""

    @patch("core.dashboard_auth.httpx.AsyncClient")
    def test_bot_oauth_rejects_bad_nonce(self, mock_client_cls, client):
        invite = _awaiting_bot_invite(nonce="correct-nonce")

        mock_client_cls.return_value = _mock_httpx(user_data=BOT_TWITCH_DATA)

        state = _build_invite_bot_state("wrong-nonce", invite.code)
        response = client.get(
            f"/auth/twitch/callback/?code=test-code&state={state}"
        )

        assert response.status_code == 400
        assert not Bot.objects.filter(twitch_user_id="149214941").exists()

    @patch("core.dashboard_auth.httpx.AsyncClient")
    def test_bot_oauth_rejects_same_account_as_channel(
        self, mock_client_cls, client
    ):
        """The bot account must differ from the channel owner account."""
        invite = _awaiting_bot_invite(
            nonce="bot-nonce-1", channel_twitch_id="149214941"
        )

        mock_client_cls.return_value = _mock_httpx(user_data=BOT_TWITCH_DATA)

        state = _build_invite_bot_state("bot-nonce-1", invite.code)
        response = client.get(
            f"/auth/twitch/callback/?code=test-code&state={state}"
        )

        assert response.status_code == 400
        invite.refresh_from_db()
        assert invite.completed_at is None

    @patch("core.synthfunc.save_token", new_callable=AsyncMock)
    @patch("core.dashboard_auth.httpx.AsyncClient")
    def test_bot_step_completes_after_expiry(
        self, mock_client_cls, mock_synthfunc, client
    ):
        """Once step 1 is done, the bot step works even past expires_at —
        expiry only gates starting onboarding, not finishing it."""
        mock_synthfunc.return_value = {"status": "ok"}

        owner = User.objects.create_user(username="owner")
        invitee = User.objects.create_user(username="spoonee")
        invite = Invite.objects.create(
            created_by=owner,
            expires_at=timezone.now() - timedelta(days=1),
            used_by=invitee,
            used_at=timezone.now() - timedelta(days=8),
            channel_twitch_id="78238052",
            channel_name="spoonee",
            channel_access_token="channel-token",
            channel_refresh_token="channel-refresh",
            channel_token_expires_at=timezone.now() - timedelta(hours=3),
            bot_oauth_nonce="bot-nonce-late",
        )
        assert invite.status == "awaiting_bot"

        mock_client_cls.return_value = _mock_httpx(user_data=BOT_TWITCH_DATA)

        state = _build_invite_bot_state("bot-nonce-late", invite.code)
        response = client.get(
            f"/auth/twitch/callback/?code=test-code&state={state}"
        )

        assert response.status_code == 200
        assert Bot.objects.filter(twitch_user_id="149214941").exists()
        invite.refresh_from_db()
        assert invite.completed_at is not None

    @patch("core.synthfunc.save_token", new_callable=AsyncMock)
    @patch("core.dashboard_auth.httpx.AsyncClient")
    def test_bot_oauth_reuses_existing_bot(
        self, mock_client_cls, mock_synthfunc, client
    ):
        mock_synthfunc.return_value = {"status": "ok"}

        existing_bot = Bot.objects.create(
            name="WorldFriendshipBot",
            twitch_user_id="149214941",
            twitch_username="worldfriendshipbot",
        )

        invite = _awaiting_bot_invite(nonce="bot-nonce-reuse")

        mock_client_cls.return_value = _mock_httpx(user_data=BOT_TWITCH_DATA)

        state = _build_invite_bot_state("bot-nonce-reuse", invite.code)
        response = client.get(
            f"/auth/twitch/callback/?code=test-code&state={state}"
        )

        assert response.status_code == 200
        assert Bot.objects.count() == 1

        existing_bot.refresh_from_db()
        assert existing_bot.access_token == "test-token"

        assert Channel.objects.filter(
            bot=existing_bot, twitch_channel_id="78238052"
        ).exists()
