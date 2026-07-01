from __future__ import annotations

import json
import logging
import secrets
from base64 import urlsafe_b64encode
from urllib.parse import urlencode

from asgiref.sync import sync_to_async
from django.conf import settings
from django.http import HttpRequest
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.shortcuts import render

from .models import Invite
from .scopes import BOT_SCOPES
from .scopes import CHANNEL_SCOPES

logger = logging.getLogger(__name__)

TWITCH_AUTHORIZE_URL = "https://id.twitch.tv/oauth2/authorize"


async def invite_landing(request: HttpRequest, code: str) -> HttpResponse:
    """Validate an invite code and show the welcome page."""
    try:
        invite = await sync_to_async(Invite.objects.get)(code=code)
    except Invite.DoesNotExist:
        return render(request, "core/invite_error.html", {
            "error": "This invite link is not valid.",
        })

    status = await sync_to_async(lambda: invite.status)()

    if status == "expired":
        return render(request, "core/invite_error.html", {
            "error": "This invite has expired. Ask the person who sent it for a new one.",
        })

    if status == "completed":
        return render(request, "core/invite_error.html", {
            "error": "This invite has already been used.",
        })

    if status == "awaiting_bot":
        return await _render_connect_bot(request, invite)

    nonce = secrets.token_urlsafe(16)
    state_data = {"nonce": nonce, "purpose": "invite", "invite_code": code}
    state = urlsafe_b64encode(json.dumps(state_data).encode()).decode()

    await sync_to_async(request.session.__setitem__)(
        "invite_oauth_nonce", nonce
    )

    redirect_uri = request.build_absolute_uri("/auth/twitch/callback/")
    oauth_url = "{}?{}".format(
        TWITCH_AUTHORIZE_URL,
        urlencode({
            "client_id": settings.TWITCH_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(CHANNEL_SCOPES),
            "force_verify": "true",
            "state": state,
        }),
    )

    return render(request, "core/invite_landing.html", {
        "invite": invite,
        "oauth_url": oauth_url,
    })


async def invite_connect_bot(request: HttpRequest, code: str) -> HttpResponse:
    """Show the bot connection page for a partially-completed invite."""
    try:
        invite = await sync_to_async(Invite.objects.get)(code=code)
    except Invite.DoesNotExist:
        return render(request, "core/invite_error.html", {
            "error": "This invite link is not valid.",
        })

    status = await sync_to_async(lambda: invite.status)()

    if status != "awaiting_bot":
        return HttpResponseRedirect(f"/invite/{code}/")

    return await _render_connect_bot(request, invite)


async def _render_connect_bot(
    request: HttpRequest, invite: Invite
) -> HttpResponse:
    """Render the bot connection page with OAuth URL for same-browser and
    a copyable link for incognito."""
    nonce = secrets.token_urlsafe(16)
    state_data = {
        "nonce": nonce,
        "purpose": "invite_bot",
        "invite_code": invite.code,
    }
    state = urlsafe_b64encode(json.dumps(state_data).encode()).decode()

    # Persist the nonce on the invite, not the session — the invitee
    # completes this step in a separate (incognito) browser with no
    # shared session, so the callback validates against the invite record.
    invite.bot_oauth_nonce = nonce
    await sync_to_async(invite.save)(update_fields=["bot_oauth_nonce"])

    redirect_uri = request.build_absolute_uri("/auth/twitch/callback/")
    oauth_url = "{}?{}".format(
        TWITCH_AUTHORIZE_URL,
        urlencode({
            "client_id": settings.TWITCH_CLIENT_ID,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(BOT_SCOPES),
            "force_verify": "true",
            "state": state,
        }),
    )

    return render(request, "core/invite_connect_bot.html", {
        "invite": invite,
        "oauth_url": oauth_url,
    })
