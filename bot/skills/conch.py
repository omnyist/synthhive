from __future__ import annotations

import random

from bot.skills import SkillHandler
from bot.skills import register_skill

DEFAULT_RESPONSES = [
    "Yes.",
    "No.",
    "Maybe someday.",
    "Try asking again.",
    "I don't think so.",
    "Definitely!",
    "Nothing.",
    "Neither.",
    "Yes, but only if you believe.",
    "No, and stop asking.",
    "Perhaps.",
    "Absolutely not.",
    "Signs point to yes.",
    "Try again later.",
]


class ConchHandler(SkillHandler):
    """Magic Conch Shell — ask a question, get a random answer.

    Skill config:
        responses (list[str]): Custom response pool. Defaults to DEFAULT_RESPONSES.
    """

    name = "conch"

    async def handle(self, payload, args, skill):
        responses = skill.config.get("responses", DEFAULT_RESPONSES)
        answer = random.choice(responses)
        await payload.respond(f"🐚 {answer}")


register_skill(ConchHandler())
