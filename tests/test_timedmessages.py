"""Timed messages — scheduling, the activity gate, and not being annoying.

The failure modes worth testing aren't "does it send". They're the ones
that make timed messages irritating: firing into an empty room, dumping
several at once, and re-sending after a failed send.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.utils import timezone

from bot import state
from bot.components.timedmessages import TimedMessages
from core.models import Bot
from core.models import Channel
from core.models import TimedMessage


@pytest.fixture
def channel(transactional_db):
    bot = Bot.objects.create(
        twitch_username="worldfriendshipbot", twitch_user_id="149214941"
    )
    return Channel.objects.create(
        bot=bot,
        twitch_channel_name="spoonee",
        twitch_channel_id="78238052",
        is_active=True,
    )


# The exact dict client.py puts in bot._channel_map. Written as a
# constant because the first version of these tests invented a
# {"name", "id"} shape: every test passed and the component raised
# KeyError('id') on the first real tick in production.
CHANNEL_INFO = {"name": "spoonee", "twitch_channel_id": "78238052"}


def _component(live=True):
    bot = MagicMock()
    bot.bot_id = "149214941"
    bot._channel_map = {"spoonee": CHANNEL_INFO}
    broadcaster = MagicMock()
    broadcaster.send_message = AsyncMock()
    bot.create_partialuser = MagicMock(return_value=broadcaster)

    component = TimedMessages(bot)
    component._is_live = AsyncMock(return_value=live)
    component._get_channel = AsyncMock(return_value=MagicMock())
    return component, broadcaster


class TestIsDue:
    """Pure scheduling logic, no I/O."""

    def test_never_sent_is_due(self, channel):
        tm = TimedMessage(channel=channel, interval_seconds=600, min_chat_lines=0)
        assert tm.is_due(timezone.now(), chat_lines=0)

    def test_disabled_is_never_due(self, channel):
        tm = TimedMessage(
            channel=channel, enabled=False, interval_seconds=0, min_chat_lines=0
        )
        assert not tm.is_due(timezone.now(), chat_lines=100)

    def test_interval_not_elapsed(self, channel):
        now = timezone.now()
        tm = TimedMessage(
            channel=channel,
            interval_seconds=1800,
            min_chat_lines=0,
            last_sent_at=now - timedelta(seconds=60),
        )
        assert not tm.is_due(now, chat_lines=100)

    def test_quiet_chat_blocks_a_due_message(self, channel):
        """The whole point of the gate — an interval elapsing is not a
        reason to talk to an empty room."""
        tm = TimedMessage(channel=channel, interval_seconds=0, min_chat_lines=5)
        assert not tm.is_due(timezone.now(), chat_lines=4)
        assert tm.is_due(timezone.now(), chat_lines=5)

    def test_gate_can_be_disabled(self, channel):
        tm = TimedMessage(channel=channel, interval_seconds=0, min_chat_lines=0)
        assert tm.is_due(timezone.now(), chat_lines=0)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestTicking:
    async def test_sends_a_due_message(self, channel):
        TimedMessage.objects.create(
            channel=channel, name="social", message="Follow me!", min_chat_lines=0
        )
        component, broadcaster = _component()
        await state.chat_activity_incr("78238052")

        await component._tick_channel(CHANNEL_INFO)

        broadcaster.send_message.assert_awaited_once()
        assert broadcaster.send_message.await_args.kwargs["message"] == "Follow me!"

    async def test_offline_sends_nothing(self, channel):
        TimedMessage.objects.create(
            channel=channel, name="social", message="Follow me!", min_chat_lines=0
        )
        component, broadcaster = _component(live=False)

        await component._tick_channel(CHANNEL_INFO)

        broadcaster.send_message.assert_not_awaited()

    async def test_only_one_message_per_tick(self, channel):
        """Three due at once must not dump into chat together."""
        for name in ("a", "b", "c"):
            TimedMessage.objects.create(
                channel=channel, name=name, message=f"msg {name}", min_chat_lines=0
            )
        component, broadcaster = _component()

        await component._tick_channel(CHANNEL_INFO)

        assert broadcaster.send_message.await_count == 1

    async def test_longest_waiting_goes_first(self, channel):
        now = timezone.now()
        TimedMessage.objects.create(
            channel=channel, name="recent", message="recent",
            min_chat_lines=0, interval_seconds=0,
            last_sent_at=now - timedelta(seconds=60),
        )
        TimedMessage.objects.create(
            channel=channel, name="stale", message="stale",
            min_chat_lines=0, interval_seconds=0,
            last_sent_at=now - timedelta(hours=3),
        )
        component, broadcaster = _component()

        await component._tick_channel(CHANNEL_INFO)

        assert broadcaster.send_message.await_args.kwargs["message"] == "stale"

    async def test_quiet_chat_sends_nothing(self, channel):
        TimedMessage.objects.create(
            channel=channel, name="social", message="Follow me!", min_chat_lines=5
        )
        component, broadcaster = _component()

        await component._tick_channel(CHANNEL_INFO)

        broadcaster.send_message.assert_not_awaited()

    async def test_sending_marks_that_messages_own_baseline(self, channel):
        tm = TimedMessage.objects.create(
            channel=channel, name="social", message="hi", min_chat_lines=1
        )
        component, _ = _component()
        for _ in range(5):
            await state.chat_activity_incr("78238052")

        await component._tick_channel(CHANNEL_INFO)

        assert await state.chat_activity_since("78238052", str(tm.id)) == 0

    async def test_one_messages_send_does_not_reset_anothers_gate(self, channel):
        """Both reviewers in the 2026-09-03 adversarial audit found this
        independently: a shared per-channel counter meant sending one
        timed message reset the gate for every other, so whichever fired
        first could starve the rest. Two messages, one already satisfied
        and due to lose the tiebreak, must not have its count zeroed by
        the other's unrelated send."""
        TimedMessage.objects.create(
            channel=channel,
            name="eager",
            message="eager message",
            min_chat_lines=0,
            interval_seconds=0,
        )
        TimedMessage.objects.create(
            channel=channel,
            name="patient",
            message="patient message",
            min_chat_lines=3,
            interval_seconds=0,
        )
        component, broadcaster = _component()

        for _ in range(3):
            await state.chat_activity_incr("78238052")

        # `eager` (alphabetically/creation-order first among equally-due
        # rows) sends first and consumes this tick.
        await component._tick_channel(CHANNEL_INFO)
        assert broadcaster.send_message.await_args.kwargs["message"] == "eager message"

        # `patient` had already seen its 3 required lines before `eager`
        # sent. Its own baseline predates all of them, so it must be
        # due immediately — not reset to zero by eager's send.
        broadcaster.send_message.reset_mock()
        await component._tick_channel(CHANNEL_INFO)
        assert broadcaster.send_message.await_args.kwargs["message"] == "patient message"

    async def test_failed_send_does_not_consume_the_slot(self, channel):
        """A send that raised must retry next tick, not silently mark
        itself sent."""
        tm = TimedMessage.objects.create(
            channel=channel, name="social", message="hi", min_chat_lines=0
        )
        component, broadcaster = _component()
        broadcaster.send_message.side_effect = RuntimeError("twitch down")

        with pytest.raises(RuntimeError):
            await component._tick_channel(CHANNEL_INFO)

        tm.refresh_from_db()
        assert tm.last_sent_at is None
        assert tm.use_count == 0

    async def test_variables_are_processed(self, channel):
        TimedMessage.objects.create(
            channel=channel,
            name="plug",
            message="Welcome to $(channel)!",
            min_chat_lines=0,
        )
        component, broadcaster = _component()

        await component._tick_channel(CHANNEL_INFO)

        assert (
            broadcaster.send_message.await_args.kwargs["message"]
            == "Welcome to spoonee!"
        )

    async def test_me_prefix_is_preserved(self, channel):
        TimedMessage.objects.create(
            channel=channel,
            name="lurk",
            message="/me - waves at chat",
            min_chat_lines=0,
        )
        component, broadcaster = _component()

        await component._tick_channel(CHANNEL_INFO)

        assert (
            broadcaster.send_message.await_args.kwargs["message"]
            == "/me waves at chat"
        )

    async def test_no_scheduled_messages_skips_the_helix_call(self, channel):
        """Don't spend a liveness check on a channel with nothing to say."""
        component, _ = _component()

        await component._tick_channel(CHANNEL_INFO)

        component._is_live.assert_not_awaited()


@pytest.mark.asyncio
async def test_router_counts_chat_towards_the_gate():
    """Ordinary conversation counts, not just commands."""
    from bot.router import CommandRouter

    bot = MagicMock()
    bot.bot_id = "149214941"
    router = CommandRouter(bot)

    payload = MagicMock()
    payload.id = "msg-1"
    payload.text = "just chatting, no command here"
    payload.chatter.id = "78238052"
    payload.broadcaster.id = "78238052"

    with patch("bot.router.state.chat_activity_incr") as incr:
        incr.return_value = None
        await router.event_message(payload)

    incr.assert_awaited_once_with("78238052")


def test_channel_info_shape_matches_what_the_client_builds():
    """Pins the fixture to the real contract.

    client.py builds _channel_map from dicts keyed by `name` and
    `twitch_channel_id`; accrual.py and lizardbullets.py both read
    `twitch_channel_id`. A test that invents its own shape proves
    nothing, which is exactly how this shipped broken.
    """
    import inspect

    from bot.components import accrual
    from bot.components import timedmessages

    for module in (accrual, timedmessages):
        src = inspect.getsource(module)
        assert 'channel_info["twitch_channel_id"]' in src, module.__name__
        assert 'channel_info["id"]' not in src, module.__name__
