"""A victim stays quotable for a few plays, then stops being named."""

from __future__ import annotations

import pytest

from bot import state

pytestmark = pytest.mark.django_db(transaction=True)


class TestVictimShelfLife:
    async def test_fresh_victim_is_current(self):
        await state.victim_set("99999", "Shinrin_Cole")
        assert await state.victim_get("99999") == "Shinrin_Cole"
        assert await state.victim_is_current("99999") is True

    async def test_survives_a_handful_of_plays(self):
        await state.victim_set("99999", "Shinrin_Cole")
        for _ in range(state.VICTIM_TTL_PLAYS):
            await state.victim_bump("99999")
        assert await state.victim_is_current("99999") is True

    async def test_expires_past_the_limit(self):
        await state.victim_set("99999", "Shinrin_Cole")
        for _ in range(state.VICTIM_TTL_PLAYS + 1):
            await state.victim_bump("99999")
        assert await state.victim_is_current("99999") is False
        # The name is still stored — callers decide not to use it.
        assert await state.victim_get("99999") == "Shinrin_Cole"

    async def test_a_new_death_restarts_the_clock(self):
        await state.victim_set("99999", "Shinrin_Cole")
        for _ in range(state.VICTIM_TTL_PLAYS + 3):
            await state.victim_bump("99999")
        assert await state.victim_is_current("99999") is False

        await state.victim_set("99999", "insanebot22")
        assert await state.victim_is_current("99999") is True
        assert await state.victim_get("99999") == "insanebot22"

    async def test_missing_counter_reads_as_expired(self):
        """Channels carrying a victim from before this counter existed —
        and any channel whose Redis was cleared — must fall back to
        naming nobody rather than claiming a stale death is current."""
        await state.get_client().set("lr:victim:99999", "Ghost")
        assert await state.victim_get("99999") == "Ghost"
        assert await state.victim_is_current("99999") is False

    async def test_channels_are_independent(self):
        await state.victim_set("111", "A")
        await state.victim_set("222", "B")
        for _ in range(state.VICTIM_TTL_PLAYS + 1):
            await state.victim_bump("111")
        assert await state.victim_is_current("111") is False
        assert await state.victim_is_current("222") is True


class TestHandlerStopsNamingExpiredVictims:
    """The point of the shelf life: the lizard stops citing a death the
    channel has long since played past."""

    def _skill(self, channel, odds):
        from core.models import Skill

        channel.owner_access_token = "fake_token"
        channel.save()
        Skill.objects.get_or_create(
            channel=channel,
            name="lizardroulette",
            defaults={"enabled": True},
        )
        Skill.objects.filter(channel=channel, name="lizardroulette").update(
            enabled=True,
            config={"odds": odds, "timeout_delay": 0, "cooldown": 0},
        )

    async def _play(self, channel, name, uid):
        from unittest.mock import AsyncMock
        from unittest.mock import MagicMock
        from unittest.mock import patch

        from bot.router import CommandRouter
        from tests.conftest import MockBroadcaster
        from tests.conftest import MockChatter
        from tests.conftest import MockPayload

        bot = MagicMock()
        bot.bot_id = "00000"
        ban = MagicMock()
        ban.status_code = 200
        payload = MockPayload(
            text="!lizardroulette",
            chatter=MockChatter(name=name, display_name=name, id=uid),
            broadcaster=MockBroadcaster(id=int(channel.twitch_channel_id)),
        )
        with patch(
            "bot.skills.lizardroulette.twitch_request",
            new_callable=AsyncMock,
            return_value=ban,
        ):
            await CommandRouter(bot).event_message(payload)
        return payload.broadcaster.send_message.call_args.kwargs["message"]

    async def test_victim_named_while_fresh_then_dropped(self, channel):
        cid = channel.twitch_channel_id

        self._skill(channel, odds=100)          # everyone dies
        await self._play(channel, "Victim1", 501)
        assert await state.victim_get(cid) == "Victim1"

        self._skill(channel, odds=0)            # everyone survives now
        fresh = await self._play(channel, "Survivor", 502)
        assert await state.victim_is_current(cid) is True

        for i in range(state.VICTIM_TTL_PLAYS + 1):
            stale = await self._play(channel, f"Other{i}", 600 + i)

        assert await state.victim_is_current(cid) is False
        assert "Victim1" not in stale, (
            f"expired victim still named: {stale!r} (fresh was {fresh!r})"
        )
