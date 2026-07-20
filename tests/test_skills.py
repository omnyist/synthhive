from __future__ import annotations

from datetime import UTC
from datetime import datetime
from datetime import timedelta
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from bot import state
from bot.skills import SKILL_REGISTRY
from bot.skills import SkillHandler
from bot.skills import discover_skills
from bot.skills.followcheck import FollowCheckHandler
from bot.skills.followcheck import format_timesince
from bot.skills.lizardmood import Mood
from bot.skills.lizardmood import MoodRoll
from bot.skills.lizardroulette import LizardRouletteHandler
from tests.conftest import MockBroadcaster
from tests.conftest import MockChatter
from tests.conftest import MockPayload

# --- Skill registry tests ---


class TestSkillRegistry:
    def test_discover_skills_runs_without_error(self):
        discover_skills()

    def test_registry_is_dict(self):
        assert isinstance(SKILL_REGISTRY, dict)

    def test_skill_handler_base_class_raises(self):
        handler = SkillHandler()
        assert handler.name == ""

    def test_discover_skills_registers_followage(self):
        discover_skills()
        assert "followage" in SKILL_REGISTRY
        assert isinstance(SKILL_REGISTRY["followage"], FollowCheckHandler)


# --- Command type dispatch tests ---
# These test the router's _resolve_response method via full event_message flow.
# Type-specific behavior tests are in test_router.py alongside text command tests.


@pytest.mark.django_db(transaction=True)
class TestLotteryType:
    async def test_lottery_success_at_100_percent(self, make_command):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter
        from tests.conftest import MockBroadcaster
        from tests.conftest import MockPayload

        make_command(
            name="flask",
            type="lottery",
            response="",
            config={
                "odds": 100,
                "success": "$(user) wins!",
                "failure": "Nope!",
            },
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        payload = MockPayload(
            text="!flask",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        payload.broadcaster.send_message.assert_called_once()
        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert msg == "TestUser wins!"

    async def test_lottery_failure_at_0_percent(self, make_command):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter

        make_command(
            name="flask",
            type="lottery",
            response="",
            config={
                "odds": 0,
                "success": "Win!",
                "failure": "You can't get ye flask, $(user)!",
            },
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        payload = MockPayload(
            text="!flask",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        payload.broadcaster.send_message.assert_called_once()
        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert msg == "You can't get ye flask, TestUser!"

    async def test_lottery_increments_use_count(self, make_command):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter

        cmd = make_command(
            name="flask",
            type="lottery",
            config={"odds": 100, "success": "Win!", "failure": "Lose!"},
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        payload = MockPayload(
            text="!flask",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        payload.broadcaster.send_message.assert_called_once()
        cmd.refresh_from_db()
        assert cmd.use_count == 1


@pytest.mark.django_db(transaction=True)
class TestCommandCooldown:
    async def test_user_cooldown_blocks_second_attempt(self, make_command):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter

        make_command(
            name="flask",
            type="lottery",
            user_cooldown_seconds=300,
            config={
                "odds": 100,
                "success": "Win!",
                "failure": "Lose!",
                "cooldown_response": "$(user), wait!",
            },
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        payload1 = MockPayload(
            text="!flask",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload1)
        payload1.broadcaster.send_message.assert_called_once()
        assert payload1.broadcaster.send_message.call_args.kwargs["message"] == "Win!"

        # Second attempt — should get cooldown response
        payload2 = MockPayload(
            text="!flask",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload2)
        payload2.broadcaster.send_message.assert_called_once()
        assert payload2.broadcaster.send_message.call_args.kwargs["message"] == "TestUser, wait!"

    async def test_cooldown_does_not_increment_use_count(self, make_command):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter

        cmd = make_command(
            name="flask",
            type="lottery",
            user_cooldown_seconds=300,
            config={
                "odds": 100,
                "success": "Win!",
                "failure": "Lose!",
                "cooldown_response": "Wait!",
            },
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        # First use — increments
        payload1 = MockPayload(
            text="!flask",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload1)
        cmd.refresh_from_db()
        assert cmd.use_count == 1

        # Second use — cooldown, no increment
        payload2 = MockPayload(
            text="!flask",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload2)
        cmd.refresh_from_db()
        assert cmd.use_count == 1

    async def test_cooldown_silent_when_no_response_configured(
        self, make_command
    ):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter

        make_command(
            name="flask",
            type="lottery",
            user_cooldown_seconds=300,
            config={
                "odds": 100,
                "success": "Win!",
                "failure": "Lose!",
            },
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        payload1 = MockPayload(
            text="!flask",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload1)
        payload1.broadcaster.send_message.assert_called_once()

        # Second attempt — no cooldown_response, so silent
        payload2 = MockPayload(
            text="!flask",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload2)
        payload2.broadcaster.send_message.assert_not_called()

    async def test_different_users_have_separate_cooldowns(
        self, make_command
    ):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter

        make_command(
            name="flask",
            type="lottery",
            user_cooldown_seconds=300,
            config={
                "odds": 100,
                "success": "$(user) wins!",
                "failure": "Lose!",
                "cooldown_response": "Wait!",
            },
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        # User A
        payload_a = MockPayload(
            text="!flask",
            chatter=MockChatter(name="usera", display_name="UserA", id=111),
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload_a)
        payload_a.broadcaster.send_message.assert_called_once()
        assert payload_a.broadcaster.send_message.call_args.kwargs["message"] == "UserA wins!"

        # User B — different user, no cooldown
        payload_b = MockPayload(
            text="!flask",
            chatter=MockChatter(name="userb", display_name="UserB", id=222),
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload_b)
        payload_b.broadcaster.send_message.assert_called_once()
        assert payload_b.broadcaster.send_message.call_args.kwargs["message"] == "UserB wins!"

    async def test_no_cooldown_when_zero(self, make_command):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter

        make_command(
            name="flask",
            type="lottery",
            config={
                "odds": 100,
                "success": "Win!",
                "failure": "Lose!",
            },
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        payload1 = MockPayload(
            text="!flask",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload1)
        payload1.broadcaster.send_message.assert_called_once()

        # No cooldown — second attempt works normally
        payload2 = MockPayload(
            text="!flask",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload2)
        payload2.broadcaster.send_message.assert_called_once()

    async def test_remaining_time_in_cooldown_response(self, make_command):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter

        make_command(
            name="flask",
            type="lottery",
            user_cooldown_seconds=3600,
            config={
                "odds": 100,
                "success": "Win!",
                "failure": "Lose!",
                "cooldown_response": "$(user), you have $(remaining) seconds left.",
            },
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        payload1 = MockPayload(
            text="!flask",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload1)
        payload1.broadcaster.send_message.assert_called_once()

        # Second attempt — should include remaining seconds
        payload2 = MockPayload(
            text="!flask",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload2)
        payload2.broadcaster.send_message.assert_called_once()
        response = payload2.broadcaster.send_message.call_args.kwargs["message"]
        # Should contain user name and raw seconds (close to 3600)
        assert response.startswith("TestUser, you have ")
        assert response.endswith(" seconds left.")
        # Extract the number and verify it's close to 3600
        seconds = int(response.split("you have ")[1].split(" seconds")[0])
        assert 3590 <= seconds <= 3600

    async def test_global_cooldown_blocks_all_users(self, make_command):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter

        make_command(
            name="shout",
            type="text",
            response="Hello!",
            cooldown_seconds=60,
            config={"cooldown_response": "Command on cooldown!"},
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        # User A triggers it
        payload_a = MockPayload(
            text="!shout",
            chatter=MockChatter(name="usera", display_name="UserA", id=111),
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload_a)
        payload_a.broadcaster.send_message.assert_called_once()
        assert payload_a.broadcaster.send_message.call_args.kwargs["message"] == "Hello!"

        # User B — blocked by global cooldown
        payload_b = MockPayload(
            text="!shout",
            chatter=MockChatter(name="userb", display_name="UserB", id=222),
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload_b)
        payload_b.broadcaster.send_message.assert_called_once()
        assert payload_b.broadcaster.send_message.call_args.kwargs["message"] == "Command on cooldown!"

    async def test_cooldown_works_on_text_commands(self, make_command):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter

        make_command(
            name="greet",
            type="text",
            response="Hi $(user)!",
            user_cooldown_seconds=30,
            config={"cooldown_response": "Slow down!"},
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        payload1 = MockPayload(
            text="!greet",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload1)
        payload1.broadcaster.send_message.assert_called_once()
        assert payload1.broadcaster.send_message.call_args.kwargs["message"] == "Hi TestUser!"

        # Second attempt — cooldown
        payload2 = MockPayload(
            text="!greet",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload2)
        payload2.broadcaster.send_message.assert_called_once()
        assert payload2.broadcaster.send_message.call_args.kwargs["message"] == "Slow down!"


@pytest.mark.django_db(transaction=True)
class TestRandomListType:
    async def test_random_list_picks_from_responses(self, make_command):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter

        responses = ["Yes.", "No.", "Maybe."]
        make_command(
            name="conch",
            type="random_list",
            config={"responses": responses},
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        payload = MockPayload(
            text="!conch question?",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        payload.broadcaster.send_message.assert_called_once()
        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert msg in responses

    async def test_random_list_with_prefix(self, make_command):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter

        make_command(
            name="conch",
            type="random_list",
            config={"prefix": "\U0001f41a ", "responses": ["Yes."]},
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        payload = MockPayload(
            text="!conch",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        payload.broadcaster.send_message.assert_called_once()
        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert msg == "\U0001f41a Yes."

    async def test_random_list_empty_responses_uses_response_field(
        self, make_command
    ):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter

        make_command(
            name="conch",
            type="random_list",
            response="No responses configured.",
            config={"responses": []},
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        payload = MockPayload(
            text="!conch",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        payload.broadcaster.send_message.assert_called_once()
        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert msg == "No responses configured."

    async def test_random_list_empty_responses_no_fallback(self, make_command):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter

        make_command(
            name="conch",
            type="random_list",
            response="",
            config={"responses": []},
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        payload = MockPayload(
            text="!conch",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        payload.broadcaster.send_message.assert_not_called()

    async def test_random_list_processes_variables(self, make_command):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter

        make_command(
            name="greet",
            type="random_list",
            config={"responses": ["Hello $(user)!"]},
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        payload = MockPayload(
            text="!greet",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        payload.broadcaster.send_message.assert_called_once()
        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert msg == "Hello TestUser!"


@pytest.mark.django_db(transaction=True)
class TestCounterType:
    async def test_counter_type_auto_increments(self, make_command, channel):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter
        from core.models import Counter

        Counter.objects.create(channel=channel, name="death", value=5)
        make_command(
            name="deaths",
            type="counter",
            response="$(count.get death) deaths so far.",
            config={"counter_name": "death"},
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        payload = MockPayload(
            text="!deaths",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        payload.broadcaster.send_message.assert_called_once()
        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert msg == "6 deaths so far."

        # Verify counter was incremented
        counter = Counter.objects.get(channel=channel, name="death")
        assert counter.value == 6

    async def test_counter_type_creates_counter_if_missing(
        self, make_command, channel
    ):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter
        from core.models import Counter

        make_command(
            name="gotcha",
            type="counter",
            response="$(count.get gotcha) bitches gotcha'd.",
            config={"counter_name": "gotcha"},
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        payload = MockPayload(
            text="!gotcha",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        # Counter should be created and incremented to 1
        counter = Counter.objects.get(channel=channel, name="gotcha")
        assert counter.value == 1

    async def test_counter_type_uses_command_name_as_default(
        self, make_command, channel
    ):
        from unittest.mock import MagicMock

        from bot.router import CommandRouter
        from core.models import Counter

        make_command(
            name="death",
            type="counter",
            response="$(count.get death)",
            config={},
        )

        bot = MagicMock()
        bot.bot_id = "00000"
        router = CommandRouter(bot)

        payload = MockPayload(
            text="!death",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        counter = Counter.objects.get(channel=channel, name="death")
        assert counter.value == 1


# --- format_timesince tests ---


class TestFormatTimesince:
    def test_seconds(self):
        now = datetime.now(UTC)
        assert format_timesince(now - timedelta(seconds=30)) == "30 seconds"

    def test_one_second(self):
        now = datetime.now(UTC)
        assert format_timesince(now - timedelta(seconds=1)) == "1 second"

    def test_minutes(self):
        now = datetime.now(UTC)
        assert format_timesince(now - timedelta(minutes=45)) == "45 minutes"

    def test_one_minute(self):
        now = datetime.now(UTC)
        assert format_timesince(now - timedelta(minutes=1)) == "1 minute"

    def test_hours(self):
        now = datetime.now(UTC)
        assert format_timesince(now - timedelta(hours=5)) == "5 hours"

    def test_one_hour(self):
        now = datetime.now(UTC)
        assert format_timesince(now - timedelta(hours=1)) == "1 hour"

    def test_days(self):
        now = datetime.now(UTC)
        assert format_timesince(now - timedelta(days=15)) == "15 days"

    def test_one_day(self):
        now = datetime.now(UTC)
        assert format_timesince(now - timedelta(days=1)) == "1 day"

    def test_months(self):
        now = datetime.now(UTC)
        assert format_timesince(now - timedelta(days=90)) == "3 months"

    def test_one_month(self):
        now = datetime.now(UTC)
        assert format_timesince(now - timedelta(days=30)) == "1 month"

    def test_years_and_months(self):
        now = datetime.now(UTC)
        assert (
            format_timesince(now - timedelta(days=450))
            == "1 year, 3 months"
        )

    def test_exact_year(self):
        now = datetime.now(UTC)
        assert format_timesince(now - timedelta(days=365)) == "1 year"

    def test_multiple_years(self):
        now = datetime.now(UTC)
        result = format_timesince(now - timedelta(days=730))
        assert result.startswith("2 years")


# --- FollowCheckHandler tests ---


def _mock_twitch_response(status_code=200, json_data=None):
    """Create a mock httpx-like response for twitch_request."""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    return response


@pytest.mark.django_db(transaction=True)
class TestFollowCheckHandler:
    async def test_following_user_gets_timesince(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel, name="followage", enabled=True
        )

        followed_at = (
            datetime.now(UTC) - timedelta(days=90)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

        api_response = _mock_twitch_response(
            json_data={
                "total": 1,
                "data": [
                    {
                        "user_id": "12345",
                        "user_login": "testuser",
                        "user_name": "TestUser",
                        "followed_at": followed_at,
                    }
                ],
            }
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!followage",
            broadcaster=MockBroadcaster(id=99999),
        )

        with patch("bot.skills.followcheck.twitch_request", new_callable=AsyncMock, return_value=api_response):
            await router.event_message(payload)

        payload.broadcaster.send_message.assert_called_once()
        response = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert response.startswith("@TestUser, you have been following for ")
        assert response.endswith("!")
        assert "3 months" in response

    async def test_not_following_user(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel, name="followage", enabled=True
        )

        api_response = _mock_twitch_response(
            json_data={"total": 0, "data": []}
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!followage",
            broadcaster=MockBroadcaster(id=99999),
        )

        with patch("bot.skills.followcheck.twitch_request", new_callable=AsyncMock, return_value=api_response):
            await router.event_message(payload)

        payload.broadcaster.send_message.assert_called_once()
        assert (
            payload.broadcaster.send_message.call_args.kwargs["message"]
            == "@TestUser, you are not following this channel."
        )

    async def test_broadcaster_gets_broadcaster_message(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel, name="followage", enabled=True
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        # Chatter ID matches broadcaster ID
        payload = MockPayload(
            text="!followage",
            chatter=MockChatter(
                name="testchannel",
                display_name="TestChannel",
                id=99999,
            ),
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        payload.broadcaster.send_message.assert_called_once()
        assert (
            payload.broadcaster.send_message.call_args.kwargs["message"]
            == "@TestChannel, you are the broadcaster!"
        )

    async def test_no_owner_token(self, channel):
        from core.models import Skill

        Skill.objects.create(
            channel=channel, name="followage", enabled=True
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!followage",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        payload.broadcaster.send_message.assert_called_once()
        assert (
            payload.broadcaster.send_message.call_args.kwargs["message"]
            == "@TestUser, follow check is not available right now."
        )

    async def test_expired_token_refresh_fails_shows_not_available(
        self, channel
    ):
        channel.owner_access_token = "expired_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel, name="followage", enabled=True
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!followage",
            broadcaster=MockBroadcaster(id=99999),
        )

        # twitch_request returns None when refresh also fails
        with patch("bot.skills.followcheck.twitch_request", new_callable=AsyncMock, return_value=None):
            await router.event_message(payload)

        payload.broadcaster.send_message.assert_called_once()
        assert (
            payload.broadcaster.send_message.call_args.kwargs["message"]
            == "@TestUser, follow check is not available right now."
        )

    async def test_skill_not_enabled_skips(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel, name="followage", enabled=False
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!followage",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        payload.broadcaster.send_message.assert_not_called()

    async def test_api_called_with_correct_url_and_params(self, channel):
        channel.owner_access_token = "test_bearer_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel, name="followage", enabled=True
        )

        followed_at = datetime.now(UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        api_response = _mock_twitch_response(
            json_data={
                "total": 1,
                "data": [
                    {
                        "user_id": "12345",
                        "user_login": "testuser",
                        "user_name": "TestUser",
                        "followed_at": followed_at,
                    }
                ],
            }
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!followage",
            broadcaster=MockBroadcaster(id=99999),
        )

        mock_twitch_request = AsyncMock(return_value=api_response)
        with patch("bot.skills.followcheck.twitch_request", mock_twitch_request):
            await router.event_message(payload)

        mock_twitch_request.assert_called_once()
        call_args = mock_twitch_request.call_args
        # First positional arg is the channel object
        assert call_args[0][1] == "GET"
        assert "channels/followers" in call_args[0][2]
        assert call_args[1]["params"]["broadcaster_id"] == "99999"
        assert call_args[1]["params"]["user_id"] == "12345"


# --- LizardRouletteHandler tests ---


def _theatrical_roll(ctx, weight_fn=None):
    """Force theatrical mood for deterministic integration tests."""
    return MoodRoll(mood=Mood.THEATRICAL, weights={}, ctx=ctx)


@pytest.mark.django_db(transaction=True)
class TestLizardRouletteHandler:
    @pytest.fixture(autouse=True)
    def _force_theatrical(self):
        # Force theatrical mood AND suppress the 3% rare-message roll so
        # integration assertions on message structure (emote, call count,
        # timeout_first) are deterministic. Rares are covered separately in
        # test_lizardmood.py. Also stub the live check to "live" so the
        # offline layer stays off and no real /streams call fires; offline
        # behavior is covered by dedicated tests that override this.
        with (
            patch(
                "bot.skills.lizardroulette.roll_mood",
                side_effect=_theatrical_roll,
            ),
            patch("bot.skills.lizardmood._try_rare", return_value=None),
            patch.object(
                LizardRouletteHandler, "_is_live", new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            yield

    def setup_method(self):
        """Clear singleton handler state between tests."""
        from bot.skills.lizardmood import recency

        discover_skills()
        recency.clear()

    def test_discover_skills_registers_lizardroulette(self):
        discover_skills()
        assert "lizardroulette" in SKILL_REGISTRY
        assert isinstance(
            SKILL_REGISTRY["lizardroulette"], LizardRouletteHandler
        )

    async def test_win_sends_success_message(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={
                "odds": 0,
                "cooldown": 0,
            },
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )

        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
        ) as mock_twitch:
            await router.event_message(payload)
            mock_twitch.assert_not_called()

        payload.broadcaster.send_message.assert_called_once()
        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "TestUser" in msg
        assert "bardLizard" in msg

    async def test_loss_sends_failure_and_timeouts(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={
                "odds": 100,
                "timeout_duration": 600,
                "timeout_delay": 0,
                "cooldown": 0,
            },
        )

        ban_response = MagicMock()
        ban_response.status_code = 200

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )

        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
            return_value=ban_response,
        ) as mock_twitch:
            await router.event_message(payload)

            # Verify failure message sent
            payload.broadcaster.send_message.assert_called_once()
            msg = payload.broadcaster.send_message.call_args.kwargs["message"]
            assert "TestUser" in msg
            assert "LizardWithAGun" in msg

            # Verify timeout API called
            mock_twitch.assert_called_once()
            call_args = mock_twitch.call_args
            assert call_args[0][1] == "POST"
            assert "moderation/bans" in call_args[0][2]
            body = call_args[1]["json"]
            assert body["data"]["user_id"] == "12345"
            assert body["data"]["duration"] == 600
            assert body["data"]["reason"] == "lizardroulette"

    async def test_per_user_cooldown_blocks_second_attempt(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={
                "odds": 0,
                "cooldown": 300,
                "cooldown_response": "$(user), wait $(remaining)s!",
            },
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        # First use — succeeds
        payload1 = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload1)
        payload1.broadcaster.send_message.assert_called_once()
        msg = payload1.broadcaster.send_message.call_args.kwargs["message"]
        assert "TestUser" in msg
        assert "bardLizard" in msg

        # Second use — cooldown
        payload2 = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload2)
        payload2.broadcaster.send_message.assert_called_once()
        response = payload2.broadcaster.send_message.call_args.kwargs[
            "message"
        ]
        assert response.startswith("TestUser, wait ")

    async def test_different_users_have_separate_cooldowns(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={
                "odds": 0,
                "cooldown": 300,
                "cooldown_response": "Wait!",
            },
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        # User A
        payload_a = MockPayload(
            text="!lizardroulette",
            chatter=MockChatter(
                name="usera", display_name="UserA", id=111
            ),
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload_a)
        payload_a.broadcaster.send_message.assert_called_once()
        msg_a = payload_a.broadcaster.send_message.call_args.kwargs["message"]
        assert "UserA" in msg_a

        # User B — different user, no cooldown
        payload_b = MockPayload(
            text="!lizardroulette",
            chatter=MockChatter(
                name="userb", display_name="UserB", id=222
            ),
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload_b)
        payload_b.broadcaster.send_message.assert_called_once()
        msg_b = payload_b.broadcaster.send_message.call_args.kwargs["message"]
        assert "UserB" in msg_b

    async def test_config_values_drive_behavior(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={
                "odds": 0,
                "cooldown": 0,
            },
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        payload.broadcaster.send_message.assert_called_once()
        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "TestUser" in msg
        assert "bardLizard" in msg

    async def test_timeout_failed_sends_fallback_message_for_broadcaster(self, channel):
        channel.owner_access_token = "fake_token"
        channel.twitch_channel_id = "12345"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={
                "odds": 100,
                "timeout_failed": "...the gun jammed. $(user) lives another day.",
                "timeout_delay": 0,
                "cooldown": 0,
            },
        )

        ban_response = MagicMock()
        ban_response.status_code = 400

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=12345),
        )

        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
            return_value=ban_response,
        ):
            await router.event_message(payload)

        calls = payload.broadcaster.send_message.call_args_list
        assert len(calls) == 2
        assert "LizardWithAGun" in calls[0].kwargs["message"]
        assert (
            calls[1].kwargs["message"]
            == "...the gun jammed. TestUser lives another day."
        )

    async def test_timeout_failed_silent_for_non_broadcaster(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={
                "odds": 100,
                "timeout_failed": "...the gun jammed. $(user) lives another day.",
                "timeout_delay": 0,
                "cooldown": 0,
            },
        )

        ban_response = MagicMock()
        ban_response.status_code = 400

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )

        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
            return_value=ban_response,
        ):
            await router.event_message(payload)

        calls = payload.broadcaster.send_message.call_args_list
        assert len(calls) == 1
        assert "LizardWithAGun" in calls[0].kwargs["message"]

    async def test_loss_tracks_death_count(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill
        from core.models import SkillStat

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={
                "odds": 100,
                "timeout_delay": 0,
                "cooldown": 0,
            },
        )

        ban_response = MagicMock()
        ban_response.status_code = 200

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        # First death
        payload1 = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )
        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
            return_value=ban_response,
        ):
            await router.event_message(payload1)

        msg1 = payload1.broadcaster.send_message.call_args.kwargs["message"]
        assert "TestUser" in msg1
        assert "LizardWithAGun" in msg1

        # Second death — death count increments
        payload2 = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )
        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
            return_value=ban_response,
        ):
            await router.event_message(payload2)

        msg2 = payload2.broadcaster.send_message.call_args.kwargs["message"]
        assert "TestUser" in msg2
        stat = SkillStat.objects.get(
            channel=channel, skill_name="lizardroulette", twitch_id="12345"
        )
        assert stat.stats["deaths"] == 2

    async def test_death_count_persists_in_skillstat(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill
        from core.models import SkillStat

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={
                "odds": 100,
                "timeout_delay": 0,
                "cooldown": 0,
            },
        )

        ban_response = MagicMock()
        ban_response.status_code = 200

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )
        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
            return_value=ban_response,
        ):
            await router.event_message(payload)

        stat = SkillStat.objects.get(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id="12345",
        )
        assert stat.stats["deaths"] == 1
        assert stat.twitch_username == "testuser"

    async def test_cross_channel_cooldowns_independent(self, bot):
        from core.models import Channel
        from core.models import Skill

        channel_a = Channel.objects.create(
            bot=bot,
            twitch_channel_id="11111",
            twitch_channel_name="channel_a",
            is_active=True,
            owner_access_token="fake",
        )
        channel_b = Channel.objects.create(
            bot=bot,
            twitch_channel_id="22222",
            twitch_channel_name="channel_b",
            is_active=True,
            owner_access_token="fake",
        )

        for ch in [channel_a, channel_b]:
            Skill.objects.create(
                channel=ch,
                name="lizardroulette",
                enabled=True,
                config={
                    "odds": 0,
                    "cooldown": 300,
                    "cooldown_response": "on cooldown!",
                },
            )

        mock_bot = MagicMock()
        mock_bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(mock_bot)

        # Play in channel A
        payload_a = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=11111),
        )
        await router.event_message(payload_a)
        msg_a = payload_a.broadcaster.send_message.call_args.kwargs["message"]
        assert "TestUser" in msg_a
        assert "bardLizard" in msg_a

        # Same user in channel B — should NOT be on cooldown
        payload_b = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=22222),
        )
        await router.event_message(payload_b)
        msg_b = payload_b.broadcaster.send_message.call_args.kwargs["message"]
        assert "TestUser" in msg_b
        assert "bardLizard" in msg_b


    async def test_bullets_guarantee_loss(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={
                "odds": 0,
                "timeout_delay": 0,
                "cooldown": 0,
            },
        )

        SKILL_REGISTRY["lizardroulette"]
        await state.bullets_set("99999", 1)

        ban_response = MagicMock()
        ban_response.status_code = 200

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )

        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
            return_value=ban_response,
        ):
            await router.event_message(payload)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "TestUser" in msg
        assert "LizardWithAGun" in msg

    async def test_bullets_decrement_on_use(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={
                "odds": 0,
                "timeout_delay": 0,
                "cooldown": 0,
            },
        )

        SKILL_REGISTRY["lizardroulette"]
        await state.bullets_set("99999", 3)

        ban_response = MagicMock()
        ban_response.status_code = 200

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )

        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
            return_value=ban_response,
        ):
            await router.event_message(payload)

        assert await state.bullets_get("99999") == 2

    async def test_bullets_exhausted_resumes_normal_odds(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={
                "odds": 0,
                "cooldown": 0,
            },
        )

        SKILL_REGISTRY["lizardroulette"]
        await state.bullets_set("99999", 0)

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )

        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
        ) as mock_twitch:
            await router.event_message(payload)
            mock_twitch.assert_not_called()

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "TestUser" in msg

    async def test_bullet_loss_tracks_death(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill
        from core.models import SkillStat

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={
                "odds": 0,
                "timeout_delay": 0,
                "cooldown": 0,
            },
        )

        SKILL_REGISTRY["lizardroulette"]
        await state.bullets_set("99999", 1)

        ban_response = MagicMock()
        ban_response.status_code = 200

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )

        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
            return_value=ban_response,
        ):
            await router.event_message(payload)

        stat = SkillStat.objects.get(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id="12345",
        )
        assert stat.stats["deaths"] == 1
        assert stat.stats["bullet_deaths"] == 1

    async def test_tracks_plays_and_survivals(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill
        from core.models import SkillStat

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={"odds": 0, "cooldown": 0},
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        stat = SkillStat.objects.get(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id="12345",
        )
        assert stat.stats["plays"] == 1
        assert stat.stats["survivals"] == 1

    async def test_tracks_streaks_broken(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill
        from core.models import SkillStat

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={"odds": 100, "timeout_delay": 0, "cooldown": 0},
        )

        SkillStat.objects.create(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id="12345",
            twitch_username="testuser",
            stats={"streak": 5},
        )

        ban_response = MagicMock()
        ban_response.status_code = 200

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )

        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
            return_value=ban_response,
        ):
            await router.event_message(payload)

        stat = SkillStat.objects.get(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id="12345",
        )
        assert stat.stats["streaks_broken"] == 1

    async def test_tracks_last_mood(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill
        from core.models import SkillStat

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={"odds": 0, "cooldown": 0},
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        stat = SkillStat.objects.get(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id="12345",
        )
        assert stat.stats["last_mood"] == "theatrical"

    async def test_win_increments_streak(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill
        from core.models import SkillStat

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={"odds": 0, "cooldown": 0},
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        for _ in range(3):
            payload = MockPayload(
                text="!lizardroulette",
                broadcaster=MockBroadcaster(id=99999),
            )
            await router.event_message(payload)

        stat = SkillStat.objects.get(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id="12345",
        )
        assert stat.stats["streak"] == 3

    async def test_death_resets_streak(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill
        from core.models import SkillStat

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={
                "odds": 100,
                "timeout_delay": 0,
                "cooldown": 0,
            },
        )

        SkillStat.objects.create(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id="12345",
            twitch_username="testuser",
            stats={"streak": 5, "deaths": 0},
        )

        ban_response = MagicMock()
        ban_response.status_code = 200
        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )

        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
            return_value=ban_response,
        ):
            await router.event_message(payload)

        stat = SkillStat.objects.get(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id="12345",
        )
        assert stat.stats["streak"] == 0
        assert stat.stats["deaths"] == 1

    async def test_broken_streak_in_failure_message(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill
        from core.models import SkillStat

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={
                "odds": 100,
                "timeout_delay": 0,
                "cooldown": 0,
            },
        )

        SkillStat.objects.create(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id="12345",
            twitch_username="testuser",
            stats={"streak": 7, "deaths": 1},
        )

        ban_response = MagicMock()
        ban_response.status_code = 200
        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )

        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
            return_value=ban_response,
        ):
            await router.event_message(payload)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "TestUser" in msg
        assert "LizardWithAGun" in msg
        stat = SkillStat.objects.get(
            channel=channel, skill_name="lizardroulette", twitch_id="12345"
        )
        assert stat.stats["streak"] == 0

    async def test_streak_tiers_escalate(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill
        from core.models import SkillStat

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={"odds": 0, "cooldown": 0},
        )

        SkillStat.objects.create(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id="12345",
            twitch_username="testuser",
            stats={"streak": 4},
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )

        await router.event_message(payload)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "5" in msg
        assert "bardLizard" in msg

    async def test_death_sets_last_victim(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={
                "odds": 100,
                "timeout_delay": 0,
                "cooldown": 0,
            },
        )

        ban_response = MagicMock()
        ban_response.status_code = 200
        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            chatter=MockChatter(
                name="victim_user", display_name="VictimUser", id=55555
            ),
            broadcaster=MockBroadcaster(id=99999),
        )

        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
            return_value=ban_response,
        ):
            await router.event_message(payload)

        SKILL_REGISTRY["lizardroulette"]
        assert await state.victim_get("99999") == "VictimUser"

    async def test_victim_in_success_message(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={"odds": 0, "cooldown": 0},
        )

        SKILL_REGISTRY["lizardroulette"]
        await state.victim_set("99999", "UnluckyPerson")

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )

        await router.event_message(payload)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "UnluckyPerson" in msg

    async def test_no_victim_omits_clause(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={"odds": 0, "cooldown": 0},
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "$(victim)" not in msg
        assert "TestUser" in msg

    async def test_self_victim_uses_self_clauses(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={"odds": 0, "cooldown": 0},
        )

        SKILL_REGISTRY["lizardroulette"]
        await state.victim_set("99999", "TestUser")

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )

        await router.event_message(payload)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "TestUser" in msg
        # Victim-only clause markers that must never appear for a self-victim.
        # ("wasn't so lucky" is intentionally excluded — a valid self_victim
        # clause reuses that phrase self-referentially.)
        for clause in ["still eating", "seat is still warm",
                       "watching from", "could never", "seething",
                       "WISHES", "rolling in", "had the decency",
                       "filing a complaint", "died so", "COOKED"]:
            assert clause not in msg

    async def test_tracks_max_streak(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill
        from core.models import SkillStat

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={"cooldown": 0},
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        # Survive twice (odds=0 → always survive)
        for _ in range(2):
            payload = MockPayload(
                text="!lizardroulette",
                broadcaster=MockBroadcaster(id=99999),
                chatter=MockChatter(id=111, name="streaker"),
            )
            with patch("bot.skills.lizardroulette.random.randint", return_value=100):
                with patch("bot.skills.lizardroulette.twitch_request", new_callable=AsyncMock):
                    await router.event_message(payload)

        stat = SkillStat.objects.get(channel=channel, twitch_id="111")
        assert stat.stats["streak"] == 2
        assert stat.stats["max_streak"] == 2

        # Die (odds=100 → always lose)
        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
            chatter=MockChatter(id=111, name="streaker"),
        )
        with patch("bot.skills.lizardroulette.random.randint", return_value=1):
            with patch("bot.skills.lizardroulette.twitch_request", new_callable=AsyncMock):
                with patch("bot.skills.lizardroulette.asyncio.sleep", new_callable=AsyncMock):
                    await router.event_message(payload)

        stat.refresh_from_db()
        assert stat.stats["streak"] == 0
        assert stat.stats["max_streak"] == 2

        # Survive once more — max_streak should stay at 2
        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
            chatter=MockChatter(id=111, name="streaker"),
        )
        with patch("bot.skills.lizardroulette.random.randint", return_value=100):
            with patch("bot.skills.lizardroulette.twitch_request", new_callable=AsyncMock):
                await router.event_message(payload)

        stat.refresh_from_db()
        assert stat.stats["streak"] == 1
        assert stat.stats["max_streak"] == 2

    async def test_play_records_lizardplay(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import LizardPlay
        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={"odds": 0, "cooldown": 0},
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)
        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        plays = list(LizardPlay.objects.filter(channel=channel))
        assert len(plays) == 1
        play = plays[0]
        assert play.outcome == "survival"  # odds=0 → always survive
        assert play.mood == "theatrical"
        assert play.is_live is True
        assert play.offline_tier == "none"  # live → no offline callout
        assert play.context["outcome"] == "survival"
        assert play.context["is_live"] is True

    async def test_birthday_mode_never_times_out(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import LizardPlay
        from core.models import Skill

        # odds=100 would normally be a guaranteed timeout.
        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={"odds": 100, "cooldown": 0, "birthday_mode": True},
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)
        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )
        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
        ) as mock_tw:
            await router.event_message(payload)

        # No timeout attempted, and no play recorded — just a message.
        mock_tw.assert_not_called()
        assert not LizardPlay.objects.filter(channel=channel).exists()
        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "birthday" in msg.lower()

    async def test_offline_play_records_offline_tier(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import LizardPlay
        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={"odds": 0, "cooldown": 0},
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)
        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )
        # Override the class fixture's live stub — this play is offline.
        with patch.object(
            LizardRouletteHandler, "_is_live",
            new_callable=AsyncMock, return_value=False,
        ):
            await router.event_message(payload)

        play = LizardPlay.objects.filter(channel=channel).first()
        assert play.is_live is False
        # Fresh user (deaths=0) → below the devotion threshold → casual.
        assert play.offline_tier == "casual"

    async def test_capture_failure_does_not_break_game(self, channel):
        channel.owner_access_token = "fake_token"
        channel.save()

        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="lizardroulette",
            enabled=True,
            config={"odds": 0, "cooldown": 0},
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)
        payload = MockPayload(
            text="!lizardroulette",
            broadcaster=MockBroadcaster(id=99999),
        )
        with patch(
            "core.models.LizardPlay.objects.create",
            side_effect=Exception("boom"),
        ):
            await router.event_message(payload)

        # A capture failure must never swallow the game response.
        assert payload.broadcaster.send_message.called


# --- Streak tier and composition tests ---




# --- Live detection tests ---


class TestLizardLiveDetection:
    def _resp(self, data):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": data}
        return resp

    async def test_live_when_stream_present(self):
        handler = LizardRouletteHandler()
        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
            return_value=self._resp([{"id": "1"}]),
        ):
            assert await handler._is_live(MagicMock(), "99999") is True

    async def test_offline_when_no_stream(self):
        handler = LizardRouletteHandler()
        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
            return_value=self._resp([]),
        ):
            assert await handler._is_live(MagicMock(), "99999") is False

    async def test_result_is_cached(self):
        handler = LizardRouletteHandler()
        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
            return_value=self._resp([]),
        ) as tr:
            await handler._is_live(MagicMock(), "99999")
            await handler._is_live(MagicMock(), "99999")
        tr.assert_called_once()

    async def test_assumes_live_on_api_failure_without_caching(self):
        handler = LizardRouletteHandler()
        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
            return_value=None,
        ) as tr:
            first = await handler._is_live(MagicMock(), "99999")
            await handler._is_live(MagicMock(), "99999")
        assert first is True
        assert tr.call_count == 2  # failures aren't cached → retries


# --- LizardBullets component tests ---


class TestLizardBulletsComponent:
    def setup_method(self):
        discover_skills()

    def _mock_skill(self, config=None):
        """Return a mock Skill with the given config dict."""
        skill = MagicMock()
        skill.config = config or {}
        return skill

    @pytest.mark.asyncio
    async def test_tick_loads_gun_on_hit(self):
        from bot.components.lizardbullets import LizardBullets

        mock_bot = MagicMock()
        mock_bot._channel_map = {
            "spoonee": {
                "name": "spoonee",
                "twitch_channel_id": "78238052",
            }
        }

        component = LizardBullets(mock_bot)

        with (
            patch.object(component, "_is_live", return_value=True),
            patch.object(component, "_get_channel", return_value=MagicMock()),
            patch(
                "bot.components.lizardbullets.sync_to_async",
                return_value=AsyncMock(return_value=self._mock_skill()),
            ),
            patch("bot.components.lizardbullets.random.randint", return_value=1),
        ):
            await component._tick_channel(mock_bot._channel_map["spoonee"])

        SKILL_REGISTRY["lizardroulette"]
        assert await state.bullets_get("78238052") == 6

    @pytest.mark.asyncio
    async def test_tick_no_load_on_miss(self):
        from bot.components.lizardbullets import LizardBullets

        mock_bot = MagicMock()
        mock_bot._channel_map = {
            "spoonee": {
                "name": "spoonee",
                "twitch_channel_id": "78238052",
            }
        }

        component = LizardBullets(mock_bot)

        with (
            patch.object(component, "_is_live", return_value=True),
            patch.object(component, "_get_channel", return_value=MagicMock()),
            patch(
                "bot.components.lizardbullets.sync_to_async",
                return_value=AsyncMock(return_value=self._mock_skill()),
            ),
            patch("bot.components.lizardbullets.random.randint", return_value=2),
        ):
            await component._tick_channel(mock_bot._channel_map["spoonee"])

        SKILL_REGISTRY["lizardroulette"]
        assert await state.bullets_get("78238052") == 0

    @pytest.mark.asyncio
    async def test_tick_skips_when_offline(self):
        from bot.components.lizardbullets import LizardBullets

        mock_bot = MagicMock()
        mock_bot._channel_map = {
            "spoonee": {
                "name": "spoonee",
                "twitch_channel_id": "78238052",
            }
        }

        component = LizardBullets(mock_bot)

        with (
            patch.object(component, "_is_live", return_value=False),
            patch.object(component, "_get_channel", return_value=MagicMock()),
            patch(
                "bot.components.lizardbullets.sync_to_async",
                return_value=AsyncMock(return_value=self._mock_skill()),
            ),
            patch("bot.components.lizardbullets.random.randint", return_value=1),
        ):
            await component._tick_channel(mock_bot._channel_map["spoonee"])

        SKILL_REGISTRY["lizardroulette"]
        assert await state.bullets_get("78238052") == 0

    @pytest.mark.asyncio
    async def test_tick_skips_when_bullets_disabled(self):
        from bot.components.lizardbullets import LizardBullets

        mock_bot = MagicMock()
        mock_bot._channel_map = {
            "spoonee": {
                "name": "spoonee",
                "twitch_channel_id": "78238052",
            }
        }

        component = LizardBullets(mock_bot)

        with (
            patch.object(component, "_is_live", return_value=True),
            patch.object(component, "_get_channel", return_value=MagicMock()),
            patch(
                "bot.components.lizardbullets.sync_to_async",
                return_value=AsyncMock(
                    return_value=self._mock_skill({"bullets_enabled": False})
                ),
            ),
            patch("bot.components.lizardbullets.random.randint", return_value=1),
        ):
            await component._tick_channel(mock_bot._channel_map["spoonee"])

        SKILL_REGISTRY["lizardroulette"]
        assert await state.bullets_get("78238052") == 0


# --- Victims skill tests ---


@pytest.mark.django_db(transaction=True)
class TestVictimsHandler:
    def setup_method(self):
        discover_skills()

    async def test_no_victims_shows_empty_message(self, channel):
        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="victims",
            enabled=True,
            config={},
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!victims",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "no victims" in msg.lower()

    async def test_shows_leaderboard(self, channel):
        from core.models import Skill
        from core.models import SkillStat

        Skill.objects.create(
            channel=channel,
            name="victims",
            enabled=True,
            config={},
        )

        SkillStat.objects.create(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id="111",
            twitch_username="playerone",
            stats={"deaths": 50, "streak": 0},
        )
        SkillStat.objects.create(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id="222",
            twitch_username="playertwo",
            stats={"deaths": 30, "streak": 2},
        )
        SkillStat.objects.create(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id="333",
            twitch_username="playerthree",
            stats={"deaths": 0, "streak": 5},
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!victims",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "digging graves" in msg
        assert "playerone" in msg
        assert "playertwo" in msg
        assert "playerthree" not in msg
        assert msg.index("playerone") < msg.index("playertwo")


@pytest.mark.django_db(transaction=True)
class TestSurvivorsHandler:
    def setup_method(self):
        discover_skills()

    async def test_no_survivors_shows_empty_message(self, channel):
        from core.models import Skill

        Skill.objects.create(
            channel=channel,
            name="survivors",
            enabled=True,
            config={},
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!survivors",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "no one has survived" in msg.lower()

    async def test_shows_leaderboard(self, channel):
        from core.models import Skill
        from core.models import SkillStat

        Skill.objects.create(
            channel=channel,
            name="survivors",
            enabled=True,
            config={},
        )

        SkillStat.objects.create(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id="111",
            twitch_username="playerone",
            stats={"deaths": 50, "streak": 0, "max_streak": 42},
        )
        SkillStat.objects.create(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id="222",
            twitch_username="playertwo",
            stats={"deaths": 30, "streak": 2, "max_streak": 15},
        )
        SkillStat.objects.create(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id="333",
            twitch_username="playerthree",
            stats={"deaths": 10, "streak": 0, "max_streak": 0},
        )

        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.router import CommandRouter

        router = CommandRouter(bot)

        payload = MockPayload(
            text="!survivors",
            broadcaster=MockBroadcaster(id=99999),
        )
        await router.event_message(payload)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "luckiest survivors" in msg
        assert "playerone" in msg
        assert "playertwo" in msg
        assert "playerthree" not in msg
        assert msg.index("playerone") < msg.index("playertwo")


# --- State durability tests (the point of Redis-backed state) ---


@pytest.mark.django_db(transaction=True)
class TestStateDurability:
    """State must survive a bot restart (deploy). A 'restart' here is a
    fresh handler instance + cleared in-memory trackers; the (fake)Redis
    backing persists across them within a test."""

    async def test_cooldown_survives_restart(self, channel):
        from bot.skills.lizardmood import recency
        from bot.skills.lizardroulette import LizardRouletteHandler

        skill = MagicMock()
        skill.config = {"cooldown": 300, "cooldown_response": "wait $(remaining)s"}
        bot = MagicMock()
        bot.bot_id = "00000"

        acquired = await state.cooldown_try_acquire("lr:cd:99999:12345", 300)
        assert acquired is True

        # "Restart": new handler instance, wiped in-memory state.
        handler = LizardRouletteHandler()
        recency.clear()

        payload = MockPayload(
            text="!lizardroulette", broadcaster=MockBroadcaster(id=99999)
        )
        await handler.handle(payload, "", skill, bot)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "wait" in msg  # still on cooldown after the "restart"

    async def test_bullets_survive_restart(self):
        await state.bullets_set("99999", 2)

        # "Restart" — bullets live in Redis, not on the handler.
        from bot.skills.lizardroulette import LizardRouletteHandler

        LizardRouletteHandler()
        assert await state.bullets_get("99999") == 2

        await state.bullets_decr("99999")
        assert await state.bullets_get("99999") == 1

    async def test_recency_hydrates_after_restart(self):
        from bot.skills.lizardmood import recency

        await state.recency_push("99999", ["fragment-alpha", "fragment-beta"])

        # "Restart": in-memory history gone, Redis persists.
        recency.clear()
        await recency.hydrate("99999")

        history = recency._history.get("99999")
        assert history is not None
        assert "fragment-alpha" in history
        assert "fragment-beta" in history

    async def test_victim_survives_restart(self):
        await state.victim_set("99999", "UnluckyPerson")
        # Nothing in-memory to clear — victims live only in Redis now.
        assert await state.victim_get("99999") == "UnluckyPerson"
