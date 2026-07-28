from __future__ import annotations

import hmac
import re
import uuid
from datetime import datetime
from datetime import timedelta
from typing import Literal

from asgiref.sync import sync_to_async
from django.db import IntegrityError
from ninja import Router
from ninja import Schema
from ninja.errors import HttpError
from ninja.pagination import paginate

from .config_validation import validate_command_config
from .config_validation import validate_skill_config
from .models import Alias
from .models import Channel
from .models import Command
from .models import Counter
from .models import Invite
from .models import Skill
from .models import TwitchProfile

v1_router = Router()

VALID_COMMAND_NAME = re.compile(r"^[a-zA-Z0-9_]+$")


# --- Auth helpers ---


async def _require_auth(request):
    """Check that the request is authenticated, raise 401 if not."""
    user = await sync_to_async(lambda: request.user)()
    is_auth = await sync_to_async(lambda: user.is_authenticated)()
    if not is_auth:
        raise HttpError(401, "Not authenticated")
    return user


async def _get_profile(user) -> TwitchProfile:
    """Get the TwitchProfile for the given user."""
    try:
        return await sync_to_async(
            TwitchProfile.objects.select_related("user").get
        )(user=user)
    except TwitchProfile.DoesNotExist:
        raise HttpError(403, "No Twitch profile linked")


async def _get_user_channel(request, channel_slug: str) -> tuple:
    """Verify the authenticated user owns this channel, or raise 403.

    Returns (channel, profile) to avoid redundant profile lookups.
    """
    user = await _require_auth(request)
    profile = await _get_profile(user)

    channel = await sync_to_async(
        Channel.objects.filter(
            twitch_channel_name=channel_slug,
            twitch_channel_id=profile.twitch_id,
            is_active=True,
        )
        .select_related("bot")
        .first
    )()

    if not channel:
        raise HttpError(404, "Channel not found")

    return channel, profile


async def _get_user_command(request, command_id: uuid.UUID) -> Command:
    """Verify the authenticated user owns this command's channel, or raise."""
    user = await _require_auth(request)
    profile = await _get_profile(user)

    try:
        cmd = await sync_to_async(
            Command.objects.select_related("channel").get
        )(pk=command_id)
    except Command.DoesNotExist:
        raise HttpError(404, "Command not found")

    if cmd.channel.twitch_channel_id != profile.twitch_id:
        raise HttpError(403, "Not authorized for this channel")

    return cmd


async def _get_user_counter(request, counter_id: uuid.UUID) -> Counter:
    """Verify the authenticated user owns this counter's channel, or raise."""
    user = await _require_auth(request)
    profile = await _get_profile(user)

    try:
        counter = await sync_to_async(
            Counter.objects.select_related("channel").get
        )(pk=counter_id)
    except Counter.DoesNotExist:
        raise HttpError(404, "Counter not found")

    if counter.channel.twitch_channel_id != profile.twitch_id:
        raise HttpError(403, "Not authorized for this channel")

    return counter


async def _get_user_alias(request, alias_id: uuid.UUID) -> Alias:
    """Verify the authenticated user owns this alias's channel, or raise."""
    user = await _require_auth(request)
    profile = await _get_profile(user)

    try:
        alias = await sync_to_async(
            Alias.objects.select_related("channel").get
        )(pk=alias_id)
    except Alias.DoesNotExist:
        raise HttpError(404, "Alias not found")

    if alias.channel.twitch_channel_id != profile.twitch_id:
        raise HttpError(403, "Not authorized for this channel")

    return alias


# --- Me ---


class ChannelBriefSchema(Schema):
    id: uuid.UUID
    name: str
    bot_name: str


class MeSchema(Schema):
    twitch_id: str
    twitch_username: str
    twitch_display_name: str
    twitch_avatar: str
    is_staff: bool
    channels: list[ChannelBriefSchema]


@v1_router.get("/me", response=MeSchema)
async def me(request):
    """Return the authenticated user's info and their channels."""
    user = await _require_auth(request)
    profile = await _get_profile(user)
    is_staff = await sync_to_async(lambda: user.is_staff)()

    channels = []
    async for channel in Channel.objects.filter(
        twitch_channel_id=profile.twitch_id, is_active=True
    ).select_related("bot"):
        channels.append(
            ChannelBriefSchema(
                id=channel.id,
                name=channel.twitch_channel_name,
                bot_name=channel.bot.name,
            )
        )

    return MeSchema(
        twitch_id=profile.twitch_id,
        twitch_username=profile.twitch_username,
        twitch_display_name=profile.twitch_display_name,
        twitch_avatar=profile.twitch_avatar,
        is_staff=is_staff,
        channels=channels,
    )


# --- Channels ---


@v1_router.get("/channels/", response=list[ChannelBriefSchema])
@paginate
async def list_channels(request):
    """List channels the authenticated user owns."""
    user = await _require_auth(request)
    profile = await _get_profile(user)

    channels = []
    async for channel in Channel.objects.filter(
        twitch_channel_id=profile.twitch_id, is_active=True
    ).select_related("bot"):
        channels.append(
            ChannelBriefSchema(
                id=channel.id,
                name=channel.twitch_channel_name,
                bot_name=channel.bot.name,
            )
        )

    return channels


# --- Commands ---


class CommandSchema(Schema):
    id: uuid.UUID
    name: str
    type: str
    response: str
    config: dict
    enabled: bool
    use_count: int
    cooldown_seconds: int
    user_cooldown_seconds: int
    mod_only: bool
    created_by: str
    created_at: datetime
    updated_at: datetime


class CommandCreateSchema(Schema):
    name: str
    type: Literal["text", "lottery", "random_list", "counter"] = "text"
    response: str = ""
    config: dict = {}
    cooldown_seconds: int = 0
    user_cooldown_seconds: int = 0
    mod_only: bool = False


class CommandUpdateSchema(Schema):
    name: str | None = None
    type: Literal["text", "lottery", "random_list", "counter"] | None = None
    response: str | None = None
    config: dict | None = None
    enabled: bool | None = None
    cooldown_seconds: int | None = None
    user_cooldown_seconds: int | None = None
    mod_only: bool | None = None


@v1_router.get(
    "/commands/channels/{channel_slug}/", response=list[CommandSchema]
)
@paginate
async def list_commands(request, channel_slug: str):
    """List all commands for a channel (including disabled)."""
    channel, _ = await _get_user_channel(request, channel_slug)

    commands = []
    async for cmd in Command.objects.filter(channel=channel).order_by("name"):
        commands.append(cmd)
    return commands


@v1_router.post("/commands/channels/{channel_slug}/", response=CommandSchema)
async def create_command(
    request, channel_slug: str, data: CommandCreateSchema
):
    """Create a command for a channel."""
    if not data.name or not VALID_COMMAND_NAME.match(data.name):
        raise HttpError(
            422, "Command name must be non-empty and contain only letters, numbers, and underscores."
        )

    channel, profile = await _get_user_channel(request, channel_slug)

    config, config_error = validate_command_config(data.type, data.config)
    if config_error:
        raise HttpError(422, f"Invalid config: {config_error}")

    try:
        cmd = await sync_to_async(Command.objects.create)(
            channel=channel,
            name=data.name,
            type=data.type,
            response=data.response,
            config=config,
            cooldown_seconds=data.cooldown_seconds,
            user_cooldown_seconds=data.user_cooldown_seconds,
            mod_only=data.mod_only,
            created_by=profile.twitch_display_name,
        )
    except IntegrityError:
        raise HttpError(409, f"Command '!{data.name}' already exists in this channel.")

    return cmd


@v1_router.get("/commands/{command_id}/", response=CommandSchema)
async def get_command(request, command_id: uuid.UUID):
    """Get a single command by ID."""
    return await _get_user_command(request, command_id)


@v1_router.patch("/commands/{command_id}/", response=CommandSchema)
async def update_command(
    request, command_id: uuid.UUID, data: CommandUpdateSchema
):
    """Update a command."""
    cmd = await _get_user_command(request, command_id)

    update_fields = []
    for field_name in [
        "name", "type", "response", "config", "enabled",
        "cooldown_seconds", "user_cooldown_seconds", "mod_only",
    ]:
        value = getattr(data, field_name)
        if value is not None:
            setattr(cmd, field_name, value)
            update_fields.append(field_name)

    if "config" in update_fields or "type" in update_fields:
        # Validate the resulting type+config combination.
        config, config_error = validate_command_config(cmd.type, cmd.config)
        if config_error:
            raise HttpError(422, f"Invalid config: {config_error}")
        cmd.config = config
        if "config" not in update_fields:
            update_fields.append("config")

    if update_fields:
        await sync_to_async(cmd.save)(update_fields=update_fields)

    return cmd


@v1_router.delete("/commands/{command_id}/")
async def delete_command(request, command_id: uuid.UUID):
    """Delete a command."""
    cmd = await _get_user_command(request, command_id)
    await sync_to_async(cmd.delete)()
    return {"success": True}


# --- Variables ---


@v1_router.get("/variables/schema/")
async def variable_schema(request):
    """Return the variable registry schema for autocomplete."""
    await _require_auth(request)

    from bot.variables import create_registry

    registry = create_registry()
    return registry.schema()


# --- Counters ---


class CounterSchema(Schema):
    id: uuid.UUID
    name: str
    label: str
    value: int


class CounterCreateSchema(Schema):
    name: str
    label: str = ""
    value: int = 0


class CounterUpdateSchema(Schema):
    name: str | None = None
    label: str | None = None
    value: int | None = None


@v1_router.get(
    "/counters/channels/{channel_slug}/", response=list[CounterSchema]
)
@paginate
async def list_counters(request, channel_slug: str):
    """List all counters for a channel."""
    channel, _ = await _get_user_channel(request, channel_slug)

    counters = []
    async for counter in Counter.objects.filter(channel=channel).order_by("name"):
        counters.append(counter)
    return counters


@v1_router.post("/counters/channels/{channel_slug}/", response=CounterSchema)
async def create_counter(
    request, channel_slug: str, data: CounterCreateSchema
):
    """Create a counter for a channel."""
    if not data.name or not VALID_COMMAND_NAME.match(data.name):
        raise HttpError(
            422, "Counter name must be non-empty and contain only letters, numbers, and underscores."
        )

    channel, _ = await _get_user_channel(request, channel_slug)

    try:
        counter = await sync_to_async(Counter.objects.create)(
            channel=channel,
            name=data.name,
            label=data.label,
            value=data.value,
        )
    except IntegrityError:
        raise HttpError(409, f"Counter '{data.name}' already exists in this channel.")

    return counter


@v1_router.patch("/counters/{counter_id}/", response=CounterSchema)
async def update_counter(
    request, counter_id: uuid.UUID, data: CounterUpdateSchema
):
    """Update a counter."""
    counter = await _get_user_counter(request, counter_id)

    update_fields = []
    for field_name in ["name", "label", "value"]:
        value = getattr(data, field_name)
        if value is not None:
            setattr(counter, field_name, value)
            update_fields.append(field_name)

    if update_fields:
        await sync_to_async(counter.save)(update_fields=update_fields)

    return counter


@v1_router.delete("/counters/{counter_id}/")
async def delete_counter(request, counter_id: uuid.UUID):
    """Delete a counter."""
    counter = await _get_user_counter(request, counter_id)
    await sync_to_async(counter.delete)()
    return {"success": True}


# --- Aliases ---


class AliasSchema(Schema):
    id: uuid.UUID
    name: str
    target: str


class AliasCreateSchema(Schema):
    name: str
    target: str


class AliasUpdateSchema(Schema):
    name: str | None = None
    target: str | None = None


@v1_router.get(
    "/aliases/channels/{channel_slug}/", response=list[AliasSchema]
)
@paginate
async def list_aliases(request, channel_slug: str):
    """List all aliases for a channel."""
    channel, _ = await _get_user_channel(request, channel_slug)

    aliases = []
    async for alias in Alias.objects.filter(channel=channel).order_by("name"):
        aliases.append(alias)
    return aliases


@v1_router.post("/aliases/channels/{channel_slug}/", response=AliasSchema)
async def create_alias(
    request, channel_slug: str, data: AliasCreateSchema
):
    """Create an alias for a channel."""
    if not data.name or not VALID_COMMAND_NAME.match(data.name):
        raise HttpError(
            422, "Alias name must be non-empty and contain only letters, numbers, and underscores."
        )

    channel, _ = await _get_user_channel(request, channel_slug)

    try:
        alias = await sync_to_async(Alias.objects.create)(
            channel=channel,
            name=data.name,
            target=data.target,
        )
    except IntegrityError:
        raise HttpError(409, f"Alias '!{data.name}' already exists in this channel.")

    return alias


@v1_router.patch("/aliases/{alias_id}/", response=AliasSchema)
async def update_alias(
    request, alias_id: uuid.UUID, data: AliasUpdateSchema
):
    """Update an alias."""
    alias = await _get_user_alias(request, alias_id)

    update_fields = []
    for field_name in ["name", "target"]:
        value = getattr(data, field_name)
        if value is not None:
            setattr(alias, field_name, value)
            update_fields.append(field_name)

    if update_fields:
        await sync_to_async(alias.save)(update_fields=update_fields)

    return alias


@v1_router.delete("/aliases/{alias_id}/")
async def delete_alias(request, alias_id: uuid.UUID):
    """Delete an alias."""
    alias = await _get_user_alias(request, alias_id)
    await sync_to_async(alias.delete)()
    return {"success": True}


# --- Skills ---


async def _get_user_skill(request, skill_id: uuid.UUID) -> Skill:
    """Verify the authenticated user owns this skill's channel, or raise."""
    user = await _require_auth(request)
    profile = await _get_profile(user)

    try:
        skill = await sync_to_async(
            Skill.objects.select_related("channel").get
        )(pk=skill_id)
    except Skill.DoesNotExist:
        raise HttpError(404, "Skill not found") from None

    if skill.channel.twitch_channel_id != profile.twitch_id:
        raise HttpError(403, "Not authorized for this channel")

    return skill


class SkillSchema(Schema):
    id: uuid.UUID
    name: str
    enabled: bool
    config: dict


class SkillCreateSchema(Schema):
    name: str
    enabled: bool = True
    config: dict = {}


class SkillUpdateSchema(Schema):
    enabled: bool | None = None
    config: dict | None = None


@v1_router.get("/skills/schema/")
async def skill_config_schemas(request):
    """JSON schema per registered skill, for config form rendering."""
    await _require_auth(request)

    from .config_validation import skill_schemas

    return skill_schemas()


@v1_router.get("/skills/channels/{channel_slug}/", response=list[SkillSchema])
@paginate
async def list_skills(request, channel_slug: str):
    """List all skills for a channel (including disabled)."""
    channel, _ = await _get_user_channel(request, channel_slug)

    skills = []
    async for skill in Skill.objects.filter(channel=channel).order_by("name"):
        skills.append(skill)
    return skills


@v1_router.post("/skills/channels/{channel_slug}/", response=SkillSchema)
async def create_skill(request, channel_slug: str, data: SkillCreateSchema):
    """Enable a skill for a channel."""
    from bot.skills import SKILL_REGISTRY
    from bot.skills import discover_skills

    discover_skills()
    if data.name not in SKILL_REGISTRY:
        raise HttpError(422, f"Unknown skill '{data.name}'.")

    channel, _ = await _get_user_channel(request, channel_slug)

    config, config_error = validate_skill_config(data.name, data.config)
    if config_error:
        raise HttpError(422, f"Invalid config: {config_error}")

    try:
        skill = await sync_to_async(Skill.objects.create)(
            channel=channel,
            name=data.name,
            enabled=data.enabled,
            config=config,
        )
    except IntegrityError:
        raise HttpError(
            409, f"Skill '{data.name}' already exists in this channel."
        ) from None

    return skill


@v1_router.patch("/skills/{skill_id}/", response=SkillSchema)
async def update_skill(request, skill_id: uuid.UUID, data: SkillUpdateSchema):
    """Update a skill's enabled state or config."""
    skill = await _get_user_skill(request, skill_id)

    update_fields = []
    if data.enabled is not None:
        skill.enabled = data.enabled
        update_fields.append("enabled")
    if data.config is not None:
        config, config_error = validate_skill_config(skill.name, data.config)
        if config_error:
            raise HttpError(422, f"Invalid config: {config_error}")
        skill.config = config
        update_fields.append("config")

    if update_fields:
        await sync_to_async(skill.save)(update_fields=update_fields)

    return skill


@v1_router.delete("/skills/{skill_id}/")
async def delete_skill(request, skill_id: uuid.UUID):
    """Remove a skill from a channel."""
    skill = await _get_user_skill(request, skill_id)
    await sync_to_async(skill.delete)()
    return {"success": True}


# --- Invites ---


class InviteSchema(Schema):
    id: uuid.UUID
    code: str
    status: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None
    completed_at: datetime | None
    channel_name: str


@v1_router.get("/invites/", response=list[InviteSchema])
async def list_invites(request):
    """List all invites created by the authenticated user."""
    user = await _require_auth(request)

    invites = []
    async for invite in Invite.objects.filter(created_by=user).order_by("-created_at"):
        invites.append(InviteSchema(
            id=invite.id,
            code=invite.code,
            status=invite.status,
            created_at=invite.created_at,
            expires_at=invite.expires_at,
            used_at=invite.used_at,
            completed_at=invite.completed_at,
            channel_name=invite.channel_name,
        ))
    return invites


@v1_router.post("/invites/", response=InviteSchema)
async def create_invite(request):
    """Create a new invite link. Returns the invite with its code."""
    user = await _require_auth(request)

    is_staff = await sync_to_async(lambda: user.is_staff)()
    if not is_staff:
        raise HttpError(403, "Only staff can create invites.")

    from django.utils import timezone

    invite = await sync_to_async(Invite.objects.create)(
        created_by=user,
        expires_at=timezone.now() + timedelta(days=7),
    )

    return InviteSchema(
        id=invite.id,
        code=invite.code,
        status=invite.status,
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        used_at=invite.used_at,
        completed_at=invite.completed_at,
        channel_name=invite.channel_name,
    )


@v1_router.delete("/invites/{invite_id}/")
async def delete_invite(request, invite_id: uuid.UUID):
    """Delete an invite."""
    user = await _require_auth(request)

    try:
        invite = await sync_to_async(Invite.objects.get)(pk=invite_id, created_by=user)
    except Invite.DoesNotExist:
        raise HttpError(404, "Invite not found") from None

    await sync_to_async(invite.delete)()
    return {"success": True}


# --- Bid wars (proxied to Synthfunc; session-auth, channel-scoped) ---


class BidWarCreateSchema(Schema):
    title: str
    options: list[str]


class BidWarAllocateSchema(Schema):
    option_id: str
    points: int | None = None
    note: str = ""
    source_event_id: str | None = None


class BidWarStatusSchema(Schema):
    status: str


@v1_router.get("/bidwars/channels/{channel_slug}/")
async def list_bid_wars_api(
    request,
    channel_slug: str,
    status: str | None = None,
    campaign_id: str | None = None,
):
    """List bid wars on the channel's active (or a specific) campaign."""
    channel, _ = await _get_user_channel(request, channel_slug)

    from .synthfunc import get_bid_wars

    wars = await get_bid_wars(
        channel.twitch_channel_name, status=status, campaign_id=campaign_id
    )
    if wars is None:
        raise HttpError(502, "Synthfunc unavailable or no active campaign.")
    return wars


@v1_router.post("/bidwars/channels/{channel_slug}/")
async def create_bid_war_api(
    request, channel_slug: str, data: BidWarCreateSchema
):
    """Create a bid war on the channel's active campaign."""
    channel, _ = await _get_user_channel(request, channel_slug)

    from .synthfunc import create_bid_war

    if len([o for o in data.options if o.strip()]) < 2:
        raise HttpError(422, "A bid war needs at least two options.")

    war = await create_bid_war(
        channel.twitch_channel_name, data.title, data.options
    )
    if war is None:
        raise HttpError(502, "Could not create bid war (no active campaign?).")
    return war


@v1_router.patch("/bidwars/channels/{channel_slug}/{bid_war_id}/")
async def update_bid_war_api(
    request, channel_slug: str, bid_war_id: str, data: BidWarStatusSchema
):
    """Open or close a bid war."""
    channel, _ = await _get_user_channel(request, channel_slug)

    from .synthfunc import set_bid_war_status

    if data.status not in ("open", "closed"):
        raise HttpError(422, "Status must be 'open' or 'closed'.")

    war = await set_bid_war_status(
        channel.twitch_channel_name, bid_war_id, data.status
    )
    if war is None:
        raise HttpError(502, "Could not update bid war.")
    return war


@v1_router.post("/bidwars/channels/{channel_slug}/{bid_war_id}/allocations/")
async def allocate_bid_war_api(
    request, channel_slug: str, bid_war_id: str, data: BidWarAllocateSchema
):
    """Allocate points to an option (negative points = correction)."""
    channel, _ = await _get_user_channel(request, channel_slug)

    from .synthfunc import allocate_bid_war_points

    if data.points == 0 and not data.source_event_id:
        raise HttpError(422, "Points must be non-zero.")

    war = await allocate_bid_war_points(
        channel.twitch_channel_name,
        bid_war_id,
        data.option_id,
        points=data.points,
        note=data.note,
        source_event_id=data.source_event_id,
    )
    if war is None:
        raise HttpError(502, "Could not record allocation.")
    return war


@v1_router.get("/bidwars/channels/{channel_slug}/{bid_war_id}/allocations/")
async def bid_war_allocations_api(
    request, channel_slug: str, bid_war_id: str, limit: int = 50
):
    """Most-recent-first allocation history."""
    channel, _ = await _get_user_channel(request, channel_slug)

    from .synthfunc import get_bid_war_allocations

    rows = await get_bid_war_allocations(
        channel.twitch_channel_name, bid_war_id, limit=limit
    )
    if rows is None:
        raise HttpError(502, "Could not fetch allocations.")
    return rows


# --- Event (active campaign, proxied to Synthfunc) ---


@v1_router.get("/campaign/channels/{channel_slug}/")
async def active_campaign_api(request, channel_slug: str):
    """The channel's active campaign with metrics and milestones, or null."""
    channel, _ = await _get_user_channel(request, channel_slug)

    from .synthfunc import get_active_campaign

    campaign = await get_active_campaign(channel.twitch_channel_name)
    return campaign  # None serializes to null — "no active event" state


@v1_router.get("/campaign/channels/{channel_slug}/gifters/")
async def gift_leaderboard_api(
    request, channel_slug: str, limit: int = 10, campaign_id: str | None = None
):
    """Top gift-sub contributors for the active (or a specific) campaign."""
    channel, _ = await _get_user_channel(request, channel_slug)

    from .synthfunc import get_gift_leaderboard

    leaderboard = await get_gift_leaderboard(
        channel.twitch_channel_name, limit=min(limit, 50), campaign_id=campaign_id
    )
    return leaderboard or []


@v1_router.get("/bidwars/channels/{channel_slug}/pending-gifts/")
async def pending_gifts_api(request, channel_slug: str):
    """Gift batches awaiting allocation on the active campaign."""
    channel, _ = await _get_user_channel(request, channel_slug)

    from .synthfunc import get_pending_gifts

    gifts = await get_pending_gifts(channel.twitch_channel_name)
    return gifts or []


# --- Campaign CRUD (proxied to Synthfunc; session-auth, channel-scoped) ---


class CampaignCreateSchema(Schema):
    name: str
    description: str = ""
    start_date: str
    end_date: str
    is_active: bool = False


class CampaignUpdateSchema(Schema):
    name: str | None = None
    description: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    is_active: bool | None = None


class MilestoneCreateSchema(Schema):
    threshold: int
    title: str
    description: str = ""
    goal_unit: str = "subs"
    is_stretch: bool = False


class MilestoneUpdateSchema(Schema):
    threshold: int | None = None
    title: str | None = None
    description: str | None = None
    goal_unit: str | None = None
    is_stretch: bool | None = None


def _relay(status: int, body: dict | list | None):
    """Pass a Synthfunc response through, relaying its error details."""
    if status == 0:
        raise HttpError(502, "Synthfunc unavailable.")
    if status >= 400:
        detail = body.get("detail") if isinstance(body, dict) else None
        raise HttpError(status, str(detail or "Synthfunc request failed."))
    return body


@v1_router.get("/campaigns/channels/{channel_slug}/")
async def list_campaigns_api(request, channel_slug: str):
    """All campaigns for the channel, with headline totals."""
    channel, _ = await _get_user_channel(request, channel_slug)

    from .synthfunc import list_campaigns

    rows = await list_campaigns(channel.twitch_channel_name)
    if rows is None:
        raise HttpError(502, "Could not fetch campaigns.")
    return rows


@v1_router.post("/campaigns/channels/{channel_slug}/")
async def create_campaign_api(request, channel_slug: str, data: CampaignCreateSchema):
    """Create a campaign (optionally activating it immediately)."""
    channel, _ = await _get_user_channel(request, channel_slug)

    from .synthfunc import create_campaign

    if not data.name.strip():
        raise HttpError(422, "Name is required.")

    status, body = await create_campaign(
        channel.twitch_channel_name, data.model_dump()
    )
    return _relay(status, body)


@v1_router.get("/campaigns/channels/{channel_slug}/{campaign_id}/")
async def campaign_detail_api(request, channel_slug: str, campaign_id: str):
    """Full detail for any campaign — including past events."""
    channel, _ = await _get_user_channel(request, channel_slug)

    from .synthfunc import get_campaign

    campaign = await get_campaign(channel.twitch_channel_name, campaign_id)
    if campaign is None:
        raise HttpError(404, "Campaign not found.")
    return campaign


@v1_router.patch("/campaigns/channels/{channel_slug}/{campaign_id}/")
async def update_campaign_api(
    request, channel_slug: str, campaign_id: str, data: CampaignUpdateSchema
):
    """Update campaign fields; activating deactivates the others."""
    channel, _ = await _get_user_channel(request, channel_slug)

    from .synthfunc import update_campaign

    status, body = await update_campaign(
        channel.twitch_channel_name, campaign_id, data.model_dump(exclude_none=True)
    )
    return _relay(status, body)


@v1_router.post("/campaigns/channels/{channel_slug}/{campaign_id}/milestones/")
async def create_milestone_api(
    request, channel_slug: str, campaign_id: str, data: MilestoneCreateSchema
):
    """Add a goal to a campaign. Returns the updated campaign."""
    channel, _ = await _get_user_channel(request, channel_slug)

    from .synthfunc import create_milestone

    status, body = await create_milestone(
        channel.twitch_channel_name, campaign_id, data.model_dump()
    )
    return _relay(status, body)


@v1_router.patch("/campaigns/channels/{channel_slug}/milestones/{milestone_id}/")
async def update_milestone_api(
    request, channel_slug: str, milestone_id: str, data: MilestoneUpdateSchema
):
    """Edit a goal. Returns the updated campaign."""
    channel, _ = await _get_user_channel(request, channel_slug)

    from .synthfunc import update_milestone

    status, body = await update_milestone(
        channel.twitch_channel_name, milestone_id, data.model_dump(exclude_none=True)
    )
    return _relay(status, body)


@v1_router.delete("/campaigns/channels/{channel_slug}/milestones/{milestone_id}/")
async def delete_milestone_api(request, channel_slug: str, milestone_id: str):
    """Remove a goal. Returns the updated campaign."""
    channel, _ = await _get_user_channel(request, channel_slug)

    from .synthfunc import delete_milestone

    status, body = await delete_milestone(
        channel.twitch_channel_name, milestone_id
    )
    return _relay(status, body)


# --- Overlay (capability-URL auth for OBS browser sources) ---
#
# These endpoints are read-only mirrors of the campaign data, gated by
# the channel's overlay_key instead of a dashboard session — a browser
# source can't (and shouldn't) hold a login. Everything served here is
# already public in chat: goal progress, war standings, gifter names.


async def _get_overlay_channel(channel_slug: str, key: str) -> Channel:
    """Resolve a channel by slug + overlay key, or 403."""
    channel = await sync_to_async(
        Channel.objects.filter(
            twitch_channel_name=channel_slug, is_active=True
        ).first
    )()
    if (
        channel is None
        or not key
        or not hmac.compare_digest(str(channel.overlay_key), key.lower())
    ):
        raise HttpError(403, "Invalid overlay key.")
    return channel


@v1_router.get("/overlay/channels/{channel_slug}/campaign/")
async def overlay_campaign_api(request, channel_slug: str, key: str = ""):
    """The active campaign for overlay widgets, or null."""
    channel = await _get_overlay_channel(channel_slug, key)

    from .synthfunc import get_active_campaign

    return await get_active_campaign(channel.twitch_channel_name)


@v1_router.get("/overlay/channels/{channel_slug}/bidwars/")
async def overlay_bid_wars_api(request, channel_slug: str, key: str = ""):
    """Bid wars on the active campaign, for overlay widgets."""
    channel = await _get_overlay_channel(channel_slug, key)

    from .synthfunc import get_bid_wars

    wars = await get_bid_wars(channel.twitch_channel_name)
    return wars or []


@v1_router.get("/overlay/channels/{channel_slug}/gifters/")
async def overlay_gifters_api(request, channel_slug: str, key: str = "", limit: int = 5):
    """Top gifters on the active campaign, for overlay widgets."""
    channel = await _get_overlay_channel(channel_slug, key)

    from .synthfunc import get_gift_leaderboard

    leaderboard = await get_gift_leaderboard(
        channel.twitch_channel_name, limit=min(limit, 25)
    )
    return leaderboard or []


@v1_router.get("/overlay/channels/{channel_slug}/urls/")
async def overlay_urls_api(request, channel_slug: str):
    """The channel's overlay key and widget paths (session auth — this
    is where the owner copies their OBS browser-source URLs from)."""
    channel, _ = await _get_user_channel(request, channel_slug)

    key = str(channel.overlay_key)
    slug = channel.twitch_channel_name
    return {
        "overlay_key": key,
        "widgets": [
            {"name": "Goals", "path": f"/overlay/{slug}/goals?key={key}"},
            {"name": "Bid war", "path": f"/overlay/{slug}/bidwar?key={key}"},
        ],
    }
