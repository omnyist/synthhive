from __future__ import annotations

import json
import logging
import secrets
from base64 import urlsafe_b64decode
from base64 import urlsafe_b64encode
from datetime import timedelta
from urllib.parse import urlencode

import httpx
from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib import auth
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.http import HttpResponseRedirect
from django.utils import timezone

from .models import Bot
from .models import Channel
from .models import Invite
from .models import TwitchProfile
from .scopes import CHANNEL_SCOPES

logger = logging.getLogger(__name__)

TWITCH_AUTHORIZE_URL = "https://id.twitch.tv/oauth2/authorize"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_USERS_URL = "https://api.twitch.tv/helix/users"


def twitch_login(request: HttpRequest) -> HttpResponse:
    """Redirect to Twitch OAuth for dashboard login."""
    nonce = secrets.token_urlsafe(16)
    state_data = {"nonce": nonce, "purpose": "dashboard"}
    state = urlsafe_b64encode(json.dumps(state_data).encode()).decode()

    request.session["dashboard_oauth_nonce"] = nonce

    redirect_uri = request.build_absolute_uri("/auth/twitch/callback/")

    params = {
        "client_id": settings.TWITCH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(CHANNEL_SCOPES),
        "force_verify": "true",
        "state": state,
    }

    return HttpResponseRedirect(f"{TWITCH_AUTHORIZE_URL}?{urlencode(params)}")


async def twitch_callback(request: HttpRequest) -> HttpResponse:
    """Handle Twitch OAuth callback. Branches on purpose:
    - "dashboard": normal login or returning user
    - "invite": channel owner connecting via invite
    - "invite_bot": bot account connecting via invite
    """
    code = request.GET.get("code")
    state_raw = request.GET.get("state")
    error = request.GET.get("error")

    if error:
        logger.error(
            "Dashboard OAuth error: %s - %s",
            error,
            request.GET.get("error_description"),
        )
        return HttpResponseBadRequest(f"Twitch authorization failed: {error}")

    if not code or not state_raw:
        return HttpResponseBadRequest("Missing authorization code or state.")

    try:
        state_data = json.loads(urlsafe_b64decode(state_raw))
    except (json.JSONDecodeError, Exception):
        return HttpResponseBadRequest("Invalid state parameter.")

    purpose = state_data.get("purpose")
    valid_purposes = ("dashboard", "invite", "invite_bot")
    if purpose not in valid_purposes:
        return HttpResponseBadRequest("Invalid state purpose.")

    # The dashboard and invite (channel) steps complete in the same browser
    # that started them, so their nonce lives in the session. The invite_bot
    # step is designed to finish in a separate incognito browser, so its
    # nonce is validated against the Invite record inside its handler.
    if purpose in ("dashboard", "invite"):
        nonce_key = {
            "dashboard": "dashboard_oauth_nonce",
            "invite": "invite_oauth_nonce",
        }[purpose]
        stored_nonce = await sync_to_async(request.session.pop)(nonce_key, None)
        if not stored_nonce or state_data.get("nonce") != stored_nonce:
            return HttpResponseBadRequest("Invalid state nonce.")

    redirect_uri = request.build_absolute_uri("/auth/twitch/callback/")

    token_data, twitch_user = await _exchange_and_fetch(code, redirect_uri)
    if token_data is None:
        return HttpResponseBadRequest("Failed to exchange authorization code.")
    if twitch_user is None:
        return HttpResponseBadRequest("Failed to fetch user info from Twitch.")

    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 3600)
    twitch_id = twitch_user["id"]
    twitch_username = twitch_user["login"]
    twitch_display_name = twitch_user["display_name"]
    twitch_avatar = twitch_user.get("profile_image_url", "")

    if purpose == "invite":
        return await _handle_invite_channel(
            request, state_data, twitch_id, twitch_username,
            twitch_display_name, twitch_avatar,
            access_token, refresh_token, expires_in,
        )

    if purpose == "invite_bot":
        return await _handle_invite_bot(
            request, state_data, twitch_id, twitch_username,
            twitch_display_name, access_token, refresh_token, expires_in,
        )

    return await _handle_dashboard_login(
        request, twitch_id, twitch_username,
        twitch_display_name, twitch_avatar,
        access_token, refresh_token, expires_in,
    )


async def _exchange_and_fetch(
    code: str, redirect_uri: str
) -> tuple[dict | None, dict | None]:
    """Exchange OAuth code for tokens and fetch Twitch user info."""
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            TWITCH_TOKEN_URL,
            data={
                "client_id": settings.TWITCH_CLIENT_ID,
                "client_secret": settings.TWITCH_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )

    if token_response.status_code != 200:
        logger.error("Token exchange failed: %s", token_response.text)
        return None, None

    token_data = token_response.json()

    async with httpx.AsyncClient() as client:
        user_response = await client.get(
            TWITCH_USERS_URL,
            headers={
                "Authorization": f"Bearer {token_data['access_token']}",
                "Client-Id": settings.TWITCH_CLIENT_ID,
            },
        )

    if user_response.status_code != 200:
        logger.error("Failed to fetch Twitch user info: %s", user_response.text)
        return token_data, None

    twitch_users = user_response.json().get("data", [])
    if not twitch_users:
        return token_data, None

    return token_data, twitch_users[0]


async def _handle_dashboard_login(
    request, twitch_id, twitch_username, twitch_display_name, twitch_avatar,
    access_token, refresh_token, expires_in,
) -> HttpResponse:
    """Standard dashboard login — check approval, create/update profile."""
    user, profile = await _get_or_create_user(
        twitch_id=twitch_id,
        twitch_username=twitch_username,
        twitch_display_name=twitch_display_name,
        twitch_avatar=twitch_avatar,
    )

    is_approved = await sync_to_async(lambda: profile.is_approved)()
    is_superuser = await sync_to_async(lambda: user.is_superuser)()
    if not is_approved and not is_superuser:
        logger.warning(
            "Dashboard login denied for %s (%s) — not approved",
            twitch_display_name,
            twitch_id,
        )
        return HttpResponseBadRequest(
            "You are not authorized to access the dashboard."
        )

    await sync_to_async(auth.login)(
        request, user, backend="django.contrib.auth.backends.ModelBackend"
    )

    await _update_channel_tokens(
        twitch_id=twitch_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )

    logger.info("Dashboard login: %s (%s)", twitch_display_name, twitch_id)
    return HttpResponseRedirect("/")


async def _handle_invite_channel(
    request, state_data, twitch_id, twitch_username,
    twitch_display_name, twitch_avatar,
    access_token, refresh_token, expires_in,
) -> HttpResponse:
    """Invite step 1: channel owner OAuth. Creates user, stores tokens on invite."""
    invite_code = state_data.get("invite_code")
    if not invite_code:
        return HttpResponseBadRequest("Missing invite code.")

    try:
        invite = await sync_to_async(Invite.objects.get)(code=invite_code)
    except Invite.DoesNotExist:
        return HttpResponseBadRequest("Invalid invite code.")

    is_redeemable = await sync_to_async(lambda: invite.is_redeemable)()
    if not is_redeemable:
        return HttpResponseBadRequest("This invite is no longer valid.")

    user, profile = await _get_or_create_user(
        twitch_id=twitch_id,
        twitch_username=twitch_username,
        twitch_display_name=twitch_display_name,
        twitch_avatar=twitch_avatar,
    )

    profile.is_approved = True
    await sync_to_async(profile.save)(update_fields=["is_approved", "updated_at"])

    invite.used_by = user
    invite.used_at = timezone.now()
    invite.channel_twitch_id = twitch_id
    invite.channel_name = twitch_username
    invite.channel_access_token = access_token
    invite.channel_refresh_token = refresh_token
    invite.channel_token_expires_at = timezone.now() + timedelta(seconds=expires_in)
    await sync_to_async(invite.save)()

    await sync_to_async(auth.login)(
        request, user, backend="django.contrib.auth.backends.ModelBackend"
    )

    logger.info(
        "Invite %s: channel owner %s (%s) connected",
        invite_code,
        twitch_display_name,
        twitch_id,
    )

    return HttpResponseRedirect(f"/invite/{invite_code}/connect-bot/")


async def _handle_invite_bot(
    request, state_data, twitch_id, twitch_username,
    twitch_display_name, access_token, refresh_token, expires_in,
) -> HttpResponse:
    """Invite step 2: bot OAuth. Creates Bot + Channel, completes onboarding."""
    invite_code = state_data.get("invite_code")
    if not invite_code:
        return HttpResponseBadRequest("Missing invite code.")

    try:
        invite = await sync_to_async(
            Invite.objects.select_related("used_by").get
        )(code=invite_code)
    except Invite.DoesNotExist:
        return HttpResponseBadRequest("Invalid invite code.")

    is_awaiting = await sync_to_async(lambda: invite.is_awaiting_bot)()
    if not is_awaiting:
        return HttpResponseBadRequest("This invite is not awaiting bot connection.")

    # Validate the nonce against the invite record (not the session), so the
    # step works when finished in a separate incognito browser.
    expected_nonce = invite.bot_oauth_nonce
    if not expected_nonce or state_data.get("nonce") != expected_nonce:
        return HttpResponseBadRequest("Invalid state nonce.")

    # The bot must be a different Twitch account than the channel owner.
    if twitch_id == invite.channel_twitch_id:
        return HttpResponseBadRequest(
            "Your bot must use a different Twitch account than your channel. "
            "Open the bot link in an incognito window and log in as the bot."
        )

    expires_at = timezone.now() + timedelta(seconds=expires_in)

    bot = await sync_to_async(Bot.objects.filter(twitch_user_id=twitch_id).first)()
    if not bot:
        bot = await sync_to_async(Bot.objects.create)(
            name=twitch_display_name,
            twitch_user_id=twitch_id,
            twitch_username=twitch_username,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=expires_at,
        )
        logger.info("Created bot: %s (%s)", twitch_display_name, twitch_id)
    else:
        bot.access_token = access_token
        bot.refresh_token = refresh_token
        bot.token_expires_at = expires_at
        await sync_to_async(bot.save)(
            update_fields=["access_token", "refresh_token", "token_expires_at"]
        )
        logger.info("Updated bot tokens: %s (%s)", bot.name, twitch_id)

    channel, ch_created = await sync_to_async(Channel.objects.get_or_create)(
        bot=bot,
        twitch_channel_id=invite.channel_twitch_id,
        defaults={
            "twitch_channel_name": invite.channel_name,
            "owner_access_token": invite.channel_access_token,
            "owner_refresh_token": invite.channel_refresh_token,
            "owner_token_expires_at": invite.channel_token_expires_at,
        },
    )

    if not ch_created:
        channel.owner_access_token = invite.channel_access_token
        channel.owner_refresh_token = invite.channel_refresh_token
        channel.owner_token_expires_at = invite.channel_token_expires_at
        await sync_to_async(channel.save)(
            update_fields=[
                "owner_access_token",
                "owner_refresh_token",
                "owner_token_expires_at",
            ]
        )

    from .synthfunc import save_token as synthfunc_save_token

    # Use the channel token's own remaining lifetime, not the bot token's.
    channel_expires_in = expires_in
    if invite.channel_token_expires_at:
        remaining = (invite.channel_token_expires_at - timezone.now()).total_seconds()
        channel_expires_in = max(int(remaining), 0)

    try:
        await synthfunc_save_token(
            user_id=invite.channel_twitch_id,
            access_token=invite.channel_access_token,
            refresh_token=invite.channel_refresh_token,
            expires_in=channel_expires_in,
        )
        logger.info(
            "Channel owner token pushed to Synthfunc for %s",
            invite.channel_twitch_id,
        )
    except Exception:
        logger.exception(
            "Failed to push channel owner token to Synthfunc for %s",
            invite.channel_twitch_id,
        )

    invite.completed_at = timezone.now()
    invite.channel_access_token = None
    invite.channel_refresh_token = None
    invite.bot_oauth_nonce = ""
    await sync_to_async(invite.save)(
        update_fields=[
            "completed_at",
            "channel_access_token",
            "channel_refresh_token",
            "bot_oauth_nonce",
        ]
    )

    logger.info(
        "Invite %s completed: bot %s in #%s",
        invite_code,
        bot.name,
        channel.twitch_channel_name,
    )

    from django.shortcuts import render

    return render(request, "core/invite_complete.html", {
        "channel_name": channel.twitch_channel_name,
        "bot_name": bot.name,
    })


async def dashboard_logout(request: HttpRequest) -> HttpResponse:
    """Log out and redirect to the login page."""
    await sync_to_async(auth.logout)(request)
    return HttpResponseRedirect("/")


async def _update_channel_tokens(
    twitch_id: str,
    access_token: str,
    refresh_token: str,
    expires_in: int,
) -> None:
    """Store channel owner tokens for all channels this user owns."""
    from .synthfunc import save_token as synthfunc_save_token

    expires_at = timezone.now() + timedelta(seconds=expires_in)

    channels = []
    async for channel in Channel.objects.filter(
        twitch_channel_id=twitch_id, is_active=True
    ):
        channels.append(channel)

    if not channels:
        return

    for channel in channels:
        channel.owner_access_token = access_token
        channel.owner_refresh_token = refresh_token
        channel.owner_token_expires_at = expires_at
        await sync_to_async(channel.save)(
            update_fields=["owner_access_token", "owner_refresh_token", "owner_token_expires_at"]
        )

        logger.info(
            "Channel owner token saved for #%s", channel.twitch_channel_name
        )

    # Push to Synthfunc as the source of truth.
    try:
        result = await synthfunc_save_token(
            user_id=twitch_id,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )
        if result:
            logger.info(
                "Channel owner token pushed to Synthfunc for %s", twitch_id
            )
        else:
            logger.warning(
                "Failed to push channel owner token to Synthfunc for %s",
                twitch_id,
            )
    except Exception:
        logger.exception(
            "Unexpected error pushing token to Synthfunc for %s", twitch_id
        )


async def _get_or_create_user(
    twitch_id: str,
    twitch_username: str,
    twitch_display_name: str,
    twitch_avatar: str,
) -> tuple:
    """Find or create a Django User + TwitchProfile for the given Twitch account."""
    from django.contrib.auth.models import User

    # Existing profile? Update and return.
    try:
        profile = await sync_to_async(
            TwitchProfile.objects.select_related("user").get
        )(twitch_id=twitch_id)
        profile.twitch_username = twitch_username
        profile.twitch_display_name = twitch_display_name
        profile.twitch_avatar = twitch_avatar
        await sync_to_async(profile.save)(
            update_fields=["twitch_username", "twitch_display_name", "twitch_avatar", "updated_at"]
        )
        return profile.user, profile
    except TwitchProfile.DoesNotExist:
        pass

    # Get or create the Django User (may already exist from seed).
    def _get_or_create_django_user():
        user, created = User.objects.get_or_create(
            username=twitch_username,
            defaults={"password": "!"},
        )
        if created:
            user.set_unusable_password()
            user.save(update_fields=["password"])
        return user

    user = await sync_to_async(_get_or_create_django_user)()

    profile = await sync_to_async(TwitchProfile.objects.create)(
        user=user,
        twitch_id=twitch_id,
        twitch_username=twitch_username,
        twitch_display_name=twitch_display_name,
        twitch_avatar=twitch_avatar,
    )

    return user, profile
