from __future__ import annotations

from django import forms
from django.contrib import admin

from .config_validation import validate_command_config
from .config_validation import validate_skill_config
from .models import Alias
from .models import Bot
from .models import Channel
from .models import Command
from .models import Counter
from .models import Invite
from .models import LizardPlay
from .models import Skill
from .models import SkillStat
from .models import TwitchProfile


class ChannelInline(admin.TabularInline):
    model = Channel
    extra = 0
    fields = [
        "twitch_channel_name",
        "twitch_channel_id",
        "is_active",
        "is_owner_connected",
    ]
    readonly_fields = ["is_owner_connected"]


@admin.register(Bot)
class BotAdmin(admin.ModelAdmin):
    list_display = ("name", "twitch_username", "twitch_user_id", "is_connected")
    search_fields = ("name", "twitch_username")
    readonly_fields = ("created_at",)
    inlines = [ChannelInline]


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = (
        "twitch_channel_name",
        "bot",
        "is_active",
        "is_owner_connected",
        "joined_at",
    )
    list_filter = ("bot", "is_active")
    search_fields = ("twitch_channel_name",)
    readonly_fields = ("joined_at",)


class CommandAdminForm(forms.ModelForm):
    class Meta:
        model = Command
        fields = [
            "channel",
            "name",
            "type",
            "response",
            "config",
            "enabled",
            "cooldown_seconds",
            "user_cooldown_seconds",
            "mod_only",
            "created_by",
        ]

    def clean(self):
        cleaned = super().clean()
        cmd_type = cleaned.get("type")
        config = cleaned.get("config") or {}
        if cmd_type:
            normalized, error = validate_command_config(cmd_type, config)
            if error:
                raise forms.ValidationError(f"Invalid config: {error}")
            cleaned["config"] = normalized
        return cleaned


@admin.register(Command)
class CommandAdmin(admin.ModelAdmin):
    form = CommandAdminForm
    list_display = (
        "name",
        "type",
        "channel",
        "enabled",
        "mod_only",
        "use_count",
        "created_by",
    )
    list_filter = ("channel", "type", "enabled", "mod_only")
    search_fields = ("name", "response")
    readonly_fields = ("use_count", "created_at", "updated_at")
    ordering = ["channel", "name"]


class SkillAdminForm(forms.ModelForm):
    class Meta:
        model = Skill
        fields = ["channel", "name", "enabled", "config"]

    def clean(self):
        cleaned = super().clean()
        name = cleaned.get("name")
        config = cleaned.get("config") or {}
        if name:
            normalized, error = validate_skill_config(name, config)
            if error:
                raise forms.ValidationError(f"Invalid config: {error}")
            cleaned["config"] = normalized
        return cleaned


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    form = SkillAdminForm
    list_display = ("name", "channel", "enabled")
    list_filter = ("channel", "enabled")
    search_fields = ("name",)
    ordering = ["channel", "name"]


@admin.register(Counter)
class CounterAdmin(admin.ModelAdmin):
    list_display = ("name", "label", "channel", "value")
    list_filter = ("channel",)
    search_fields = ("name", "label")
    ordering = ["channel", "name"]


@admin.register(LizardPlay)
class LizardPlayAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "twitch_username",
        "channel",
        "outcome",
        "mood",
        "is_live",
        "is_scripted",
        "was_bullet",
        "deaths",
    )
    list_filter = ("channel", "outcome", "mood", "is_live", "is_scripted")
    search_fields = ("twitch_username", "twitch_id")
    ordering = ["-created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SkillStat)
class SkillStatAdmin(admin.ModelAdmin):
    list_display = (
        "skill_name",
        "twitch_username",
        "channel",
        "plays",
        "deaths",
        "survivals",
        "streak",
        "max_streak",
        "last_mood",
    )
    list_filter = ("channel", "skill_name")
    search_fields = ("twitch_username", "twitch_id")
    ordering = ["channel", "skill_name", "twitch_username"]


@admin.register(Alias)
class AliasAdmin(admin.ModelAdmin):
    list_display = ("name", "target", "channel")
    list_filter = ("channel",)
    search_fields = ("name", "target")
    ordering = ["channel", "name"]


@admin.register(TwitchProfile)
class TwitchProfileAdmin(admin.ModelAdmin):
    list_display = (
        "twitch_display_name",
        "twitch_username",
        "twitch_id",
        "is_approved",
    )
    list_filter = ("is_approved",)
    search_fields = ("twitch_username", "twitch_display_name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ("code", "status", "created_by", "channel_name", "created_at")
    list_filter = ("created_at",)
    search_fields = ("code", "channel_name")
    readonly_fields = ("code", "created_at", "used_at", "completed_at")
