from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from typing import ClassVar

if TYPE_CHECKING:
    import twitchio
    from pydantic import BaseModel
    from twitchio.ext import commands

    from core.models import Channel
    from core.models import Skill

logger = logging.getLogger("bot")


class SkillHandler:
    """Base class for skill implementations.

    Each handler owns a skill name that matches a Skill.name in the DB.
    The CommandRouter dispatches to the handler when a matching skill
    is found and enabled for the channel.

    Handlers with configurable behavior declare a `config_schema`
    (pydantic model, extra="forbid") — the single source of truth for
    keys, types, bounds, and tenant-neutral defaults. Config is
    validated against it at every write path (API, admin); handlers
    still read config with .get() defaults so sparse rows keep working.
    """

    name: str = ""
    config_schema: ClassVar[type[BaseModel] | None] = None

    async def handle(
        self,
        payload: twitchio.ChatMessage,
        args: str,
        skill: Skill,
        bot: commands.Bot,
        channel: Channel,
    ) -> None:
        """Handle one invocation of this skill.

        `channel` is passed rather than read off `skill.channel` so the
        relation is never lazy-loaded in async context — reaching
        through the model only worked because the router happened to
        fetch with select_related, which is a promise no signature made.
        """
        raise NotImplementedError


SKILL_REGISTRY: dict[str, SkillHandler] = {}


def register_skill(handler: SkillHandler) -> None:
    """Register a skill handler by name."""
    SKILL_REGISTRY[handler.name] = handler
    logger.debug("Registered skill handler: %s", handler.name)


def discover_skills() -> None:
    """Import all skill modules to trigger registration.

    Simple behaviors (conch, flask, counter) are now command types
    handled inline by the router. This function registers only
    complex Python-coded skill handlers.
    """
    from bot.skills import addicts  # noqa: F401
    from bot.skills import ads  # noqa: F401
    from bot.skills import campaigns  # noqa: F401
    from bot.skills import cute  # noqa: F401
    from bot.skills import dungeon  # noqa: F401
    from bot.skills import followcheck  # noqa: F401
    from bot.skills import give  # noqa: F401
    from bot.skills import lizardroulette  # noqa: F401
    from bot.skills import markov  # noqa: F401
    from bot.skills import punt  # noqa: F401
    from bot.skills import quotes  # noqa: F401
    from bot.skills import survivors  # noqa: F401
    from bot.skills import victims  # noqa: F401
    from bot.skills import wallet  # noqa: F401
