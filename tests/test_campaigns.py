from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

from bot.skills.campaigns import CampaignHandler
from bot.skills.campaigns import TimerHandler
from tests.conftest import MockPayload


def _make_skill(channel_name="testchannel"):
    """A skill mock carrying just what campaign handlers read."""
    skill = MagicMock()
    skill.channel.twitch_channel_name = channel_name
    return skill


def _make_bot():
    bot = MagicMock()
    bot.bot_id = "00000"
    return bot


class TestTimerHandler:
    async def test_timer_mode_true_shows_status(self):
        """Regression: timer_mode is a BOOLEAN from Synthfunc — the handler
        used to compare it to the string "countdown" and always bail."""
        campaign = {
            "name": "Subathon",
            "timer_mode": True,
            "metric": {
                "timer_seconds_remaining": 3725,
                "timer_started_at": "2026-07-20T00:00:00Z",
                "timer_paused_at": None,
            },
        }
        payload = MockPayload(text="!timer")

        with patch(
            "bot.skills.campaigns.get_active_campaign",
            new_callable=AsyncMock,
            return_value=campaign,
        ):
            await TimerHandler().handle(payload, "", _make_skill(), _make_bot())

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "1h 2m 5s" in msg
        assert "RUNNING" in msg

    async def test_timer_mode_false_says_no_timer(self):
        campaign = {"name": "Plain", "timer_mode": False, "metric": {}}
        payload = MockPayload(text="!timer")

        with patch(
            "bot.skills.campaigns.get_active_campaign",
            new_callable=AsyncMock,
            return_value=campaign,
        ):
            await TimerHandler().handle(payload, "", _make_skill(), _make_bot())

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "doesn't have a timer" in msg

    async def test_paused_timer_reports_paused(self):
        campaign = {
            "name": "Subathon",
            "timer_mode": True,
            "metric": {
                "timer_seconds_remaining": 90,
                "timer_started_at": "2026-07-20T00:00:00Z",
                "timer_paused_at": "2026-07-20T01:00:00Z",
            },
        }
        payload = MockPayload(text="!timer")

        with patch(
            "bot.skills.campaigns.get_active_campaign",
            new_callable=AsyncMock,
            return_value=campaign,
        ):
            await TimerHandler().handle(payload, "", _make_skill(), _make_bot())

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "1m 30s" in msg
        assert "PAUSED" in msg

    async def test_no_campaign(self):
        payload = MockPayload(text="!timer")

        with patch(
            "bot.skills.campaigns.get_active_campaign",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await TimerHandler().handle(payload, "", _make_skill(), _make_bot())

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "No active campaign" in msg


class TestCampaignHandler:
    async def test_shows_subs_and_milestones(self):
        campaign = {
            "name": "Anniversary",
            "metric": {"total_subs": 120, "total_resubs": 45},
            "milestones": [
                {"is_unlocked": True},
                {"is_unlocked": True},
                {"is_unlocked": False},
            ],
        }
        payload = MockPayload(text="!campaign")

        with patch(
            "bot.skills.campaigns.get_active_campaign",
            new_callable=AsyncMock,
            return_value=campaign,
        ):
            await CampaignHandler().handle(payload, "", _make_skill(), _make_bot())

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "Anniversary: 120 subs, 45 resubs" in msg
        assert "2/3 milestones unlocked" in msg
