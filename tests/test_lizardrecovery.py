"""Tests for the pending-timeout journal and its startup recovery."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from bot import state
from bot.components.lizardrecovery import LizardRecovery
from bot.skills import SKILL_REGISTRY
from bot.skills import discover_skills
from tests.conftest import MockBroadcaster
from tests.conftest import MockPayload

pytestmark = pytest.mark.django_db(transaction=True)


class TestPendingTimeoutState:
    async def test_add_all_clear_round_trip(self):
        await state.pending_timeout_add("99999", "555", "victim", 600, 1234.5)
        entries = await state.pending_timeouts_all()
        assert entries == [
            {
                "username": "victim",
                "duration": 600,
                "due_at": 1234.5,
                "channel_id": "99999",
                "twitch_id": "555",
            }
        ]

        await state.pending_timeout_clear("99999", "555")
        assert await state.pending_timeouts_all() == []


class TestDeathJournalsPendingTimeout:
    def _lizard_skill(self, channel):
        from core.models import Skill

        channel.owner_access_token = "fake_token"
        channel.save()
        return Skill.objects.create(
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

    async def test_death_journals_then_clears_after_ban(self, channel):
        self._lizard_skill(channel)

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

        with (
            patch(
                "bot.skills.lizardroulette.twitch_request",
                new_callable=AsyncMock,
                return_value=ban_response,
            ),
            patch(
                "bot.state.pending_timeout_add",
                new_callable=AsyncMock,
            ) as mock_add,
            patch(
                "bot.state.pending_timeout_clear",
                new_callable=AsyncMock,
            ) as mock_clear,
        ):
            await router.event_message(payload)

        mock_add.assert_awaited_once()
        args = mock_add.await_args.args
        assert args[0] == "99999"  # broadcaster
        assert args[3] == 600  # duration
        assert mock_add.await_args.kwargs["due_at"] == pytest.approx(
            time.time(), abs=5
        )
        mock_clear.assert_awaited_once()


class TestLizardRecovery:
    def _make_component(self, bot_twitch_id="66977097"):
        bot = MagicMock()
        bot.bot_id = bot_twitch_id
        broadcaster = MagicMock()
        broadcaster.send_message = AsyncMock()
        bot.create_partialuser.return_value = broadcaster
        return LizardRecovery(bot), broadcaster

    async def test_delivers_fresh_pending_timeout(self, channel):
        discover_skills()
        await state.pending_timeout_add(
            "99999", "555", "victim", 600, due_at=time.time() - 5
        )
        component, broadcaster = self._make_component()

        with patch.object(
            SKILL_REGISTRY["lizardroulette"],
            "_timeout_user",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_ban:
            await component._sweep()

        args = mock_ban.await_args.args
        assert args[0].twitch_channel_id == "99999"
        assert args[1:] == ("99999", "555", 600)
        assert await state.pending_timeouts_all() == []

        message = broadcaster.send_message.call_args.kwargs["message"]
        assert "never forgets" in message
        assert "victim" in message

    async def test_stale_entry_dropped_without_ban(self, channel):
        discover_skills()
        await state.pending_timeout_add(
            "99999", "555", "victim", 600, due_at=time.time() - 700
        )
        component, broadcaster = self._make_component()

        with patch.object(
            SKILL_REGISTRY["lizardroulette"],
            "_timeout_user",
            new_callable=AsyncMock,
        ) as mock_ban:
            await component._sweep()

        mock_ban.assert_not_awaited()
        broadcaster.send_message.assert_not_called()
        assert await state.pending_timeouts_all() == []

    async def test_failed_delivery_keeps_entry(self, channel):
        discover_skills()
        await state.pending_timeout_add(
            "99999", "555", "victim", 600, due_at=time.time() - 5
        )
        component, broadcaster = self._make_component()

        with patch.object(
            SKILL_REGISTRY["lizardroulette"],
            "_timeout_user",
            new_callable=AsyncMock,
            return_value=False,
        ):
            await component._sweep()

        broadcaster.send_message.assert_not_called()
        assert len(await state.pending_timeouts_all()) == 1

    async def test_other_bots_channels_left_alone(self, channel):
        discover_skills()
        await state.pending_timeout_add(
            "88888", "555", "victim", 600, due_at=time.time() - 5
        )
        component, _ = self._make_component()

        with patch.object(
            SKILL_REGISTRY["lizardroulette"],
            "_timeout_user",
            new_callable=AsyncMock,
        ) as mock_ban:
            await component._sweep()

        mock_ban.assert_not_awaited()
        assert len(await state.pending_timeouts_all()) == 1
