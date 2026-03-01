from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from bot.skills import SKILL_REGISTRY
from bot.skills import discover_skills
from bot.skills.conch import ConchHandler
from bot.skills.conch import DEFAULT_RESPONSES
from bot.skills.counter import CounterHandler
from bot.skills.flask import FlaskHandler
from tests.conftest import MockBroadcaster
from tests.conftest import MockChatter
from tests.conftest import MockPayload


# --- Skill registry tests ---


class TestSkillRegistry:
    def test_discover_skills_populates_registry(self):
        discover_skills()
        assert "conch" in SKILL_REGISTRY
        assert "getyeflask" in SKILL_REGISTRY
        assert "count" in SKILL_REGISTRY

    def test_handler_types(self):
        discover_skills()
        assert isinstance(SKILL_REGISTRY["conch"], ConchHandler)
        assert isinstance(SKILL_REGISTRY["getyeflask"], FlaskHandler)
        assert isinstance(SKILL_REGISTRY["count"], CounterHandler)


# --- Conch skill tests ---


class TestConchHandler:
    async def test_responds_with_default_response(self):
        handler = ConchHandler()
        payload = MockPayload()
        skill = _mock_skill(config={})

        await handler.handle(payload, "Will it rain?", skill)

        payload.respond.assert_called_once()
        response = payload.respond.call_args[0][0]
        assert response.startswith("🐚 ")
        # Strip emoji prefix and check it's a valid response
        answer = response[2:].strip()
        assert answer in DEFAULT_RESPONSES

    async def test_uses_custom_responses_from_config(self):
        handler = ConchHandler()
        payload = MockPayload()
        custom = ["Always.", "Never."]
        skill = _mock_skill(config={"responses": custom})

        await handler.handle(payload, "question", skill)

        response = payload.respond.call_args[0][0]
        answer = response[2:].strip()
        assert answer in custom


# --- Flask skill tests ---


class TestFlaskHandler:
    async def test_success_message(self):
        handler = FlaskHandler()
        payload = MockPayload(
            chatter=MockChatter(name="Bryan"),
        )
        # Set odds to 100% for deterministic success
        skill = _mock_skill(config={
            "odds": 100,
            "success": "{user} got ye flask! 🎉",
            "failure": "Nope.",
        })

        await handler.handle(payload, "", skill)

        payload.respond.assert_called_once_with("Bryan got ye flask! 🎉")

    async def test_failure_message(self):
        handler = FlaskHandler()
        payload = MockPayload(
            chatter=MockChatter(name="Bryan"),
        )
        # Set odds to 0% for deterministic failure
        skill = _mock_skill(config={
            "odds": 0,
            "failure": "You can't get ye flask!",
        })

        await handler.handle(payload, "", skill)

        payload.respond.assert_called_once_with("You can't get ye flask!")

    async def test_default_config(self):
        handler = FlaskHandler()
        payload = MockPayload(
            chatter=MockChatter(name="Tester"),
        )
        skill = _mock_skill(config={})

        await handler.handle(payload, "", skill)

        payload.respond.assert_called_once()
        response = payload.respond.call_args[0][0]
        assert "Tester" in response or "flask" in response.lower()

    async def test_no_chatter_uses_someone(self):
        handler = FlaskHandler()
        payload = MockPayload(chatter=None)
        skill = _mock_skill(config={"odds": 100, "success": "{user} won!"})

        await handler.handle(payload, "", skill)

        payload.respond.assert_called_once_with("someone won!")


# --- Counter skill tests ---


@pytest.mark.django_db(transaction=True)
class TestCounterHandler:
    async def test_show_counter_value(self, make_counter):
        make_counter(name="death", value=5, label="Death Count")
        handler = CounterHandler()
        payload = _counter_payload()

        await handler.handle(payload, "death", _mock_skill())

        payload.respond.assert_called_once_with("Death Count: 5")

    async def test_show_missing_counter(self, channel):
        handler = CounterHandler()
        payload = _counter_payload()

        await handler.handle(payload, "nonexistent", _mock_skill())

        payload.respond.assert_called_once_with(
            "Counter 'nonexistent' does not exist."
        )

    async def test_increment_creates_counter(self, channel):
        handler = CounterHandler()
        payload = _counter_payload(moderator=True)

        await handler.handle(payload, "death +", _mock_skill())

        payload.respond.assert_called_once()
        response = payload.respond.call_args[0][0]
        assert "Death: 1" in response

    async def test_increment_existing_counter(self, make_counter):
        make_counter(name="death", value=10, label="Deaths")
        handler = CounterHandler()
        payload = _counter_payload(moderator=True)

        await handler.handle(payload, "death +", _mock_skill())

        payload.respond.assert_called_once_with("Deaths: 11")

    async def test_decrement(self, make_counter):
        make_counter(name="death", value=10, label="Deaths")
        handler = CounterHandler()
        payload = _counter_payload(moderator=True)

        await handler.handle(payload, "death -", _mock_skill())

        payload.respond.assert_called_once_with("Deaths: 9")

    async def test_set_value(self, make_counter):
        make_counter(name="death", value=10, label="Deaths")
        handler = CounterHandler()
        payload = _counter_payload(moderator=True)

        await handler.handle(payload, "death set 42", _mock_skill())

        payload.respond.assert_called_once_with("Deaths: 42")

    async def test_set_invalid_value(self, channel):
        handler = CounterHandler()
        payload = _counter_payload(moderator=True)

        await handler.handle(payload, "death set abc", _mock_skill())

        payload.respond.assert_called_once_with("Value must be a number.")

    async def test_set_missing_value(self, channel):
        handler = CounterHandler()
        payload = _counter_payload(moderator=True)

        await handler.handle(payload, "death set", _mock_skill())

        payload.respond.assert_called_once_with("Usage: !count <name> set <N>")

    async def test_no_args_shows_usage(self, channel):
        handler = CounterHandler()
        payload = _counter_payload()

        await handler.handle(payload, "", _mock_skill())

        payload.respond.assert_called_once_with(
            "Usage: !count <name> [+|-|set <N>]"
        )

    async def test_non_mod_cannot_increment(self, make_counter):
        make_counter(name="death", value=10)
        handler = CounterHandler()
        # Regular user, not a mod
        payload = _counter_payload(moderator=False)

        await handler.handle(payload, "death +", _mock_skill())

        payload.respond.assert_not_called()

    async def test_label_falls_back_to_title(self, channel):
        handler = CounterHandler()
        payload = _counter_payload(moderator=True)

        await handler.handle(payload, "scare +", _mock_skill())

        payload.respond.assert_called_once()
        response = payload.respond.call_args[0][0]
        # Label defaults to name.title()
        assert response.startswith("Scare:")


# --- Helpers ---


class _MockSkillConfig:
    """Minimal skill mock with config dict access."""

    def __init__(self, config=None):
        self.config = config or {}


def _mock_skill(config=None):
    return _MockSkillConfig(config=config)


def _counter_payload(moderator=False):
    """Create a payload for counter tests with the right broadcaster ID."""
    return MockPayload(
        chatter=MockChatter(
            name="testuser",
            moderator=moderator,
            broadcaster=False,
        ),
        broadcaster=MockBroadcaster(id=99999),
    )
