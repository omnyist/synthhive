from __future__ import annotations

import secrets
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from encrypted_fields import EncryptedTextField


class TwitchProfile(models.Model):
    """Links a Django User to their Twitch identity for dashboard auth.

    Designed for multi-provider support — a DiscordProfile can be added
    later alongside this, both linked to the same Django User.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="twitch_profile",
    )
    twitch_id = models.CharField(max_length=50, unique=True, db_index=True)
    twitch_username = models.CharField(max_length=100)
    twitch_display_name = models.CharField(max_length=100)
    twitch_avatar = models.CharField(max_length=500, blank=True, default="")
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.twitch_display_name} ({self.twitch_id})"


def _generate_invite_code():
    return secrets.token_urlsafe(8)


class Invite(models.Model):
    """A one-time invite link for onboarding a new tenant.

    The flow is two-step: channel owner OAuth, then bot OAuth.
    Channel owner tokens are stored temporarily on the invite
    until the bot is connected and the Channel record is created.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=16, unique=True, default=_generate_invite_code)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_invites",
    )
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()

    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="used_invites",
    )
    used_at = models.DateTimeField(null=True, blank=True)

    channel_twitch_id = models.CharField(max_length=50, blank=True, default="")
    channel_name = models.CharField(max_length=100, blank=True, default="")
    channel_access_token = EncryptedTextField(null=True, blank=True)
    channel_refresh_token = EncryptedTextField(null=True, blank=True)
    channel_token_expires_at = models.DateTimeField(null=True, blank=True)

    # Nonce for the bot OAuth step. Stored on the invite (not the session)
    # so the step works across browsers — the invitee authorizes the bot
    # account in an incognito window with no shared session.
    bot_oauth_nonce = models.CharField(max_length=64, blank=True, default="")

    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Invite {self.code} ({self.status})"

    @property
    def status(self) -> str:
        # Expiry gates *starting* onboarding, not finishing it. Once step 1 is
        # done (used_at set), the invitee can always complete the bot step —
        # the awaiting_bot state doesn't expire out from under them.
        if self.completed_at:
            return "completed"
        if self.used_at:
            return "awaiting_bot"
        if self.expires_at < timezone.now():
            return "expired"
        return "pending"

    @property
    def is_redeemable(self) -> bool:
        return self.status == "pending"

    @property
    def is_awaiting_bot(self) -> bool:
        return self.status == "awaiting_bot"


class Bot(models.Model):
    """Bot identity (e.g., Elsydeon, WorldFriendshipBot).

    Each bot connects to Twitch with its own credentials and speaks
    in one or more channels.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100)
    twitch_user_id = models.CharField(max_length=50, unique=True)
    twitch_username = models.CharField(max_length=100)

    access_token = EncryptedTextField(null=True, blank=True)
    refresh_token = EncryptedTextField(null=True, blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.name

    @property
    def is_connected(self) -> bool:
        return bool(self.access_token)


class Channel(models.Model):
    """A channel where a bot is active.

    Stores both the channel identity and the channel owner's OAuth tokens,
    which are needed for moderation actions.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    bot = models.ForeignKey(Bot, on_delete=models.CASCADE, related_name="channels")
    twitch_channel_id = models.CharField(max_length=50)
    twitch_channel_name = models.CharField(max_length=100)

    owner_access_token = EncryptedTextField(null=True, blank=True)
    owner_refresh_token = EncryptedTextField(null=True, blank=True)
    owner_token_expires_at = models.DateTimeField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(default=timezone.now)

    # Capability token for OBS overlay URLs — grants read-only access to
    # campaign data without a dashboard session. Rotate by assigning a
    # new uuid4 if a URL ever leaks on stream.
    overlay_key = models.UUIDField(default=uuid.uuid4)

    class Meta:
        unique_together = ["bot", "twitch_channel_id"]

    def __str__(self):
        return f"{self.bot.name} in #{self.twitch_channel_name}"

    @property
    def is_owner_connected(self) -> bool:
        return bool(self.owner_access_token)


class Command(models.Model):
    """A command triggered by !name in chat.

    The type determines how the response is chosen and what side effects happen:
    - text: Static response template from `response` field
    - lottery: Roll odds, pick success or failure from `config`
    - random_list: Random pick from `config["responses"]`
    - counter: Auto-increment a named counter, then respond with `response` template

    Response text supports variables like $(user), $(channel), $(uses).
    """

    class Type(models.TextChoices):
        TEXT = "text", "Text"
        LOTTERY = "lottery", "Lottery"
        RANDOM_LIST = "random_list", "Random List"
        COUNTER = "counter", "Counter"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(
        Channel, on_delete=models.CASCADE, related_name="commands"
    )
    name = models.CharField(max_length=100)
    type = models.CharField(max_length=20, choices=Type, default=Type.TEXT)
    response = models.TextField(blank=True, default="")
    config = models.JSONField(default=dict, blank=True)

    enabled = models.BooleanField(default=True)
    use_count = models.PositiveIntegerField(default=0)
    cooldown_seconds = models.PositiveIntegerField(default=0)
    user_cooldown_seconds = models.PositiveIntegerField(default=0)
    mod_only = models.BooleanField(default=False)

    created_by = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["channel", "name"]
        ordering = ["name"]

    def __str__(self):
        return f"!{self.name} in #{self.channel.twitch_channel_name}"


class Skill(models.Model):
    """A Python-implemented command toggled per channel.

    The actual logic lives in bot/skills/ as Python handler classes.
    This model controls whether the skill is enabled for a channel
    and provides per-channel configuration via the config JSON field.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(
        Channel, on_delete=models.CASCADE, related_name="skills"
    )
    name = models.CharField(max_length=50)
    enabled = models.BooleanField(default=True)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ["channel", "name"]
        ordering = ["name"]

    def __str__(self):
        status = "enabled" if self.enabled else "disabled"
        return f"!{self.name} ({status}) in #{self.channel.twitch_channel_name}"


class Counter(models.Model):
    """A named counter per channel (death count, scare count, etc.).

    Stored as a dedicated model (not Skill.config JSON) so we can use
    Django F() expressions for atomic increments and provide direct
    admin editing.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(
        Channel, on_delete=models.CASCADE, related_name="counters"
    )
    name = models.CharField(max_length=100)
    label = models.CharField(max_length=100, blank=True, default="")
    value = models.IntegerField(default=0)

    class Meta:
        unique_together = ["channel", "name"]
        ordering = ["name"]

    def __str__(self):
        display = self.label or self.name.title()
        return f"{display}: {self.value} in #{self.channel.twitch_channel_name}"


class SkillStat(models.Model):
    """Per-user stats for a skill in a channel.

    Counter-style stats are real integer columns so they can be
    incremented atomically with F() expressions and ordered/filtered in
    the database (leaderboards) — the JSON read-modify-write pattern
    lost increments under concurrency and forced Python-side sorting.
    The `stats` JSONField remains for future arbitrary per-skill data
    that isn't counter-shaped.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(
        Channel, on_delete=models.CASCADE, related_name="skill_stats"
    )
    skill_name = models.CharField(max_length=50)
    twitch_id = models.CharField(max_length=50)
    twitch_username = models.CharField(max_length=100, blank=True, default="")

    plays = models.PositiveIntegerField(default=0)
    deaths = models.PositiveIntegerField(default=0)
    survivals = models.PositiveIntegerField(default=0)
    streak = models.PositiveIntegerField(default=0)
    max_streak = models.PositiveIntegerField(default=0)
    bullet_deaths = models.PositiveIntegerField(default=0)
    streaks_broken = models.PositiveIntegerField(default=0)
    last_mood = models.CharField(max_length=20, blank=True, default="")

    stats = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ["channel", "skill_name", "twitch_id"]
        ordering = ["skill_name", "twitch_username"]

    def __str__(self):
        return f"{self.skill_name} stats for {self.twitch_username or self.twitch_id} in #{self.channel.twitch_channel_name}"


class LizardPlay(models.Model):
    """Append-only log of every lizardroulette play.

    One row per play, written at outcome resolution. Captures the mood
    roll (chosen mood + full weight distribution), the context that drove
    it, and the outcome — the training signal for engagement-weighted
    moods. SkillStat holds running totals; this holds the per-play record
    those totals can't reconstruct.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(
        Channel, on_delete=models.CASCADE, related_name="lizard_plays"
    )
    twitch_id = models.CharField(max_length=50, db_index=True)
    twitch_username = models.CharField(max_length=100, blank=True, default="")

    outcome = models.CharField(max_length=20)  # "death" or "survival"
    was_bullet = models.BooleanField(default=False)
    is_scripted = models.BooleanField(default=False)
    is_live = models.BooleanField(default=True)
    offline_tier = models.CharField(  # "none", "casual", or "devotion"
        max_length=20, default="none"
    )

    mood = models.CharField(max_length=20)
    message = models.TextField(blank=True, default="")
    mood_weights = models.JSONField(default=dict, blank=True)

    deaths = models.IntegerField(default=0)
    streak = models.IntegerField(default=0)
    max_streak = models.IntegerField(default=0)

    context = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["channel", "twitch_id", "created_at"]),
        ]

    def __str__(self):
        return f"{self.twitch_username} {self.outcome} ({self.mood}) @ {self.created_at:%Y-%m-%d %H:%M}"


class DungeonWager(models.Model):
    """Journal of every dungeon wager, written at debit time.

    The dungeon's live game state is an in-memory asyncio task, so a
    deploy mid-game would otherwise eat wagers that were already
    debited. This journal is the durable money record: entries start
    pending, are marked won/lost at resolution, and any still pending
    at bot startup are orphans from a killed game — refunded by
    DungeonRecovery.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        WON = "won", "Won"
        LOST = "lost", "Lost"
        REFUNDED = "refunded", "Refunded"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(
        Channel, on_delete=models.CASCADE, related_name="dungeon_wagers"
    )
    game_key = models.CharField(max_length=32, db_index=True)
    twitch_id = models.CharField(max_length=50)
    twitch_username = models.CharField(max_length=100, blank=True, default="")
    display_name = models.CharField(max_length=100, blank=True, default="")
    wager = models.PositiveIntegerField()
    payout = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=10, choices=Status, default=Status.PENDING
    )
    created_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["channel", "status"]),
        ]

    def __str__(self):
        return (
            f"{self.display_name or self.twitch_id} wagered {self.wager} "
            f"({self.status}) in #{self.channel.twitch_channel_name}"
        )


class Alias(models.Model):
    """A type-agnostic command alias per channel.

    Resolved early in the message pipeline — rewrites the trigger to
    the target text before routing. Works for both text commands and
    skills transparently.

    Example: name="ct", target="count death" rewrites !ct → !count death.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    channel = models.ForeignKey(
        Channel, on_delete=models.CASCADE, related_name="aliases"
    )
    name = models.CharField(max_length=100)
    target = models.CharField(max_length=200)

    class Meta:
        unique_together = ["channel", "name"]
        ordering = ["name"]

    def __str__(self):
        return f"!{self.name} → !{self.target} in #{self.channel.twitch_channel_name}"
