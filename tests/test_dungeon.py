from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from bot.skills import SKILL_REGISTRY
from bot.skills import discover_skills
from bot.skills.dungeon import DungeonHandler
from tests.conftest import MockBroadcaster
from tests.conftest import MockChatter
from tests.conftest import MockPayload


@pytest.fixture(autouse=True)
def _clear_dungeon_state():
    """Clear singleton handler state between tests."""
    discover_skills()
    handler = SKILL_REGISTRY["dungeon"]
    handler._games.clear()
    handler._cooldowns.clear()


@pytest.fixture
async def _dungeon_env():
    """Async test environment for the dungeon handler.

    Yields an entry gate (asyncio.Event). The entry timer (the _sleep
    call with the test config's entry_duration=0) blocks on the gate, so
    the game task cannot race ahead and close entry while a test is
    still joining players — handle() genuinely suspends on journal DB
    writes, which hands the loop to the game task. Tests that resolve a
    game call `.set()` on the gate before awaiting game.task; resolution
    pauses (3/2/1s) run instantly.

    On teardown, cancels + awaits any background game task the test left
    running — undrained tasks hang event-loop teardown. Applied only to
    the async classes (an async autouse fixture collides with the sync
    helper tests).
    """
    handler = SKILL_REGISTRY["dungeon"]
    entry_gate = asyncio.Event()

    async def fake_sleep(self, seconds):
        if seconds == 0:  # entry timer (test config entry_duration=0)
            await entry_gate.wait()
        # resolution pauses: instant

    with patch.object(DungeonHandler, "_sleep", fake_sleep):
        yield entry_gate
        tasks = [g.task for g in list(handler._games.values()) if g.task]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(BaseException):
                await task
    handler._games.clear()
    handler._cooldowns.clear()


def _make_skill(channel):
    """Create a dungeon skill with fast config for testing."""
    from core.models import Skill

    return Skill.objects.create(
        channel=channel,
        name="dungeon",
        enabled=True,
        config={
            "entry_duration": 0,
            "cooldown": 300,
            "min_wager": 10,
            "max_wager": 10000,
            "currency_name": "spoons",
            "levels": [
                {"name": "Cactuar Village", "min_players": 1, "survival_chance": 70, "multiplier": 1.5},
                {"name": "Tonberry Cove", "min_players": 3, "survival_chance": 60, "multiplier": 1.75},
                {"name": "Ultros", "min_players": 6, "survival_chance": 50, "multiplier": 2.0},
            ],
        },
    )


def _transact_success(*args, **kwargs):
    """Mock transact_wallets that always succeeds."""
    return {"processed": 1, "failed": []}


def _transact_insufficient(*args, **kwargs):
    """Mock transact_wallets that reports insufficient funds."""
    return {"processed": 0, "failed": [{"twitch_id": "12345", "error": "insufficient_funds"}]}


class TestDungeonRegistry:
    def test_discover_skills_registers_dungeon(self):
        discover_skills()
        assert "dungeon" in SKILL_REGISTRY
        assert isinstance(SKILL_REGISTRY["dungeon"], DungeonHandler)


class TestDungeonHelpers:
    def test_get_level_single_player(self):
        levels = [
            {"name": "A", "min_players": 1, "survival_chance": 70, "multiplier": 1.5},
            {"name": "B", "min_players": 3, "survival_chance": 60, "multiplier": 1.75},
        ]
        assert DungeonHandler._get_level(1, levels)["name"] == "A"
        assert DungeonHandler._get_level(2, levels)["name"] == "A"
        assert DungeonHandler._get_level(3, levels)["name"] == "B"
        assert DungeonHandler._get_level(10, levels)["name"] == "B"

    def test_format_name_list_short(self):
        names = ["Alice", "Bob", "Charlie"]
        result = DungeonHandler._format_name_list(names)
        assert result == "Alice, Bob, Charlie"

    def test_format_name_list_empty(self):
        assert DungeonHandler._format_name_list([]) == ""

    def test_format_name_list_single(self):
        assert DungeonHandler._format_name_list(["Alice"]) == "Alice"

    def test_format_name_list_truncates_long_lists(self):
        names = [f"Player{i}" for i in range(100)]
        result = DungeonHandler._format_name_list(names, max_chars=50)
        assert "and" in result
        assert "more" in result
        assert len(result) <= 60


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("_dungeon_env")
class TestDungeonEntryPhase:
    async def test_no_wager_sends_usage(self, channel):
        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        payload = MockPayload(
            text="!dungeon",
            broadcaster=MockBroadcaster(id=99999),
        )

        await handler.handle(payload, "", skill, bot)

        payload.broadcaster.send_message.assert_called_once()
        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "specify a wager" in msg.lower() or "usage" in msg.lower()

    async def test_invalid_wager_sends_error(self, channel):
        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        payload = MockPayload(
            text="!dungeon abc",
            broadcaster=MockBroadcaster(id=99999),
        )

        await handler.handle(payload, "abc", skill, bot)

        payload.broadcaster.send_message.assert_called_once()
        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "10" in msg and "10000" in msg

    async def test_wager_below_minimum(self, channel):
        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        payload = MockPayload(
            text="!dungeon 5",
            broadcaster=MockBroadcaster(id=99999),
        )

        await handler.handle(payload, "5", skill, bot)

        payload.broadcaster.send_message.assert_called_once()
        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "10" in msg

    async def test_wager_above_maximum(self, channel):
        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        payload = MockPayload(
            text="!dungeon 99999",
            broadcaster=MockBroadcaster(id=99999),
        )

        await handler.handle(payload, "99999", skill, bot)

        payload.broadcaster.send_message.assert_called_once()
        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "10000" in msg

    async def test_insufficient_funds(self, channel):
        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        payload = MockPayload(
            text="!dungeon 500",
            broadcaster=MockBroadcaster(id=99999),
        )

        with patch(
            "bot.skills.dungeon.transact_wallets",
            new_callable=AsyncMock,
            return_value=_transact_insufficient(),
        ):
            await handler.handle(payload, "500", skill, bot)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "enough" in msg.lower() or "insufficient" in msg.lower()

    async def test_successful_entry_starts_game(self, channel):
        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        payload = MockPayload(
            text="!dungeon 500",
            broadcaster=MockBroadcaster(id=99999),
        )

        with patch(
            "bot.skills.dungeon.transact_wallets",
            new_callable=AsyncMock,
            return_value=_transact_success(),
        ):
            await handler.handle(payload, "500", skill, bot)
            # Game was created
            assert "99999" in handler._games
            game = handler._games["99999"]
            assert game.phase == "entry"
            assert "12345" in game.participants
            assert game.participants["12345"].wager == 500

            # Cancel the background task to prevent it from running
            game.task.cancel()
            try:
                await game.task
            except asyncio.CancelledError:
                pass

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "500" in msg
        assert "spoons" in msg

    async def test_second_player_joins_existing_game(self, channel):
        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        broadcaster = MockBroadcaster(id=99999)

        payload1 = MockPayload(
            text="!dungeon 500",
            chatter=MockChatter(name="player1", display_name="Player1", id=111),
            broadcaster=broadcaster,
        )
        payload2 = MockPayload(
            text="!dungeon 200",
            chatter=MockChatter(name="player2", display_name="Player2", id=222),
            broadcaster=broadcaster,
        )

        with patch(
            "bot.skills.dungeon.transact_wallets",
            new_callable=AsyncMock,
            return_value=_transact_success(),
        ):
            await handler.handle(payload1, "500", skill, bot)
            await handler.handle(payload2, "200", skill, bot)

            game = handler._games["99999"]
            assert len(game.participants) == 2
            assert game.participants["222"].wager == 200

            game.task.cancel()
            try:
                await game.task
            except asyncio.CancelledError:
                pass

    async def test_already_joined_prevents_double_entry(self, channel):
        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        broadcaster = MockBroadcaster(id=99999)

        payload1 = MockPayload(
            text="!dungeon 500",
            broadcaster=broadcaster,
        )

        with patch(
            "bot.skills.dungeon.transact_wallets",
            new_callable=AsyncMock,
            return_value=_transact_success(),
        ) as mock_transact:
            await handler.handle(payload1, "500", skill, bot)

            # Same user tries again
            payload2 = MockPayload(
                text="!dungeon 300",
                broadcaster=MockBroadcaster(id=99999),
            )
            await handler.handle(payload2, "300", skill, bot)

            # Transact called only once (first entry)
            assert mock_transact.call_count == 1

            game = handler._games["99999"]
            game.task.cancel()
            try:
                await game.task
            except asyncio.CancelledError:
                pass

        msg = payload2.broadcaster.send_message.call_args.kwargs["message"]
        assert "already" in msg.lower()


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("_dungeon_env")
class TestDungeonCooldown:
    async def test_cooldown_blocks_new_game(self, channel):
        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        # Simulate a recent game completion
        import time

        handler._cooldowns["99999"] = time.monotonic()

        payload = MockPayload(
            text="!dungeon 500",
            broadcaster=MockBroadcaster(id=99999),
        )

        with patch(
            "bot.skills.dungeon.transact_wallets",
            new_callable=AsyncMock,
        ) as mock_transact:
            await handler.handle(payload, "500", skill, bot)
            mock_transact.assert_not_called()

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "cooldown" in msg.lower() or "wait" in msg.lower()


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("_dungeon_env")
class TestDungeonResolution:
    async def test_solo_win_pays_out(self, channel, _dungeon_env):
        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        broadcaster = MockBroadcaster(id=99999)
        payload = MockPayload(
            text="!dungeon 100",
            broadcaster=broadcaster,
        )

        with patch(
            "bot.skills.dungeon.transact_wallets",
            new_callable=AsyncMock,
            return_value=_transact_success(),
        ) as mock_transact, patch(
            "bot.skills.dungeon.random.randint",
            return_value=1,
        ):
            await handler.handle(payload, "100", skill, bot)
            # Wait for the background task (entry_duration=0)
            game = handler._games.get("99999")
            _dungeon_env.set()
            if game and game.task:
                await game.task

            # Transact called twice: deduct + payout
            assert mock_transact.call_count == 2
            payout_call = mock_transact.call_args_list[1]
            entries = payout_call[0][1]
            assert entries[0]["amount"] == "150"
            assert payout_call[1]["reason"] == "dungeon_payout"

    async def test_solo_loss_no_payout(self, channel, _dungeon_env):
        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        broadcaster = MockBroadcaster(id=99999)
        payload = MockPayload(
            text="!dungeon 100",
            broadcaster=broadcaster,
        )

        with patch(
            "bot.skills.dungeon.transact_wallets",
            new_callable=AsyncMock,
            return_value=_transact_success(),
        ) as mock_transact, patch(
            "bot.skills.dungeon.random.randint",
            return_value=100,
        ):
            await handler.handle(payload, "100", skill, bot)
            game = handler._games.get("99999")
            _dungeon_env.set()
            if game and game.task:
                await game.task

            # Transact called only once (deduct), no payout
            assert mock_transact.call_count == 1

    async def test_group_game_with_mixed_outcomes(self, channel, _dungeon_env):
        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        broadcaster = MockBroadcaster(id=99999)

        # Track random.randint calls to control per-player survival
        roll_results = iter([1, 100, 1])

        with patch(
            "bot.skills.dungeon.transact_wallets",
            new_callable=AsyncMock,
            return_value=_transact_success(),
        ) as mock_transact, patch(
            "bot.skills.dungeon.random.randint",
            side_effect=roll_results,
        ):
            for i in range(3):
                payload = MockPayload(
                    text=f"!dungeon {100 * (i + 1)}",
                    chatter=MockChatter(name=f"p{i}", display_name=f"P{i}", id=1000 + i),
                    broadcaster=broadcaster,
                )
                await handler.handle(payload, str(100 * (i + 1)), skill, bot)

            game = handler._games.get("99999")
            _dungeon_env.set()
            if game and game.task:
                await game.task

            # 3 deducts + 1 payout call for winners
            assert mock_transact.call_count == 4

            payout_call = mock_transact.call_args_list[3]
            entries = payout_call[0][1]
            # 2 survivors (rolls 1 and 1, survival_chance=60 for Tonberry Cove)
            assert len(entries) == 2

    async def test_game_clears_after_completion(self, channel, _dungeon_env):
        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        broadcaster = MockBroadcaster(id=99999)
        payload = MockPayload(
            text="!dungeon 100",
            broadcaster=broadcaster,
        )

        with patch(
            "bot.skills.dungeon.transact_wallets",
            new_callable=AsyncMock,
            return_value=_transact_success(),
        ), patch(
            "bot.skills.dungeon.random.randint",
            return_value=1,
        ):
            await handler.handle(payload, "100", skill, bot)
            game = handler._games.get("99999")
            _dungeon_env.set()
            if game and game.task:
                await game.task

        # Game cleared from active games
        assert "99999" not in handler._games
        # Cooldown set
        assert "99999" in handler._cooldowns

    async def test_wipe_outcome_sends_wipe_message(self, channel, _dungeon_env):
        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        broadcaster = MockBroadcaster(id=99999)

        with patch(
            "bot.skills.dungeon.transact_wallets",
            new_callable=AsyncMock,
            return_value=_transact_success(),
        ), patch(
            "bot.skills.dungeon.random.randint",
            return_value=100,
        ):
            for i in range(3):
                payload = MockPayload(
                    text="!dungeon 100",
                    chatter=MockChatter(name=f"p{i}", display_name=f"P{i}", id=2000 + i),
                    broadcaster=broadcaster,
                )
                await handler.handle(payload, "100", skill, bot)

            game = handler._games.get("99999")
            _dungeon_env.set()
            if game and game.task:
                await game.task

        # Check that a wipe message was sent (no reply_to)
        broadcast_calls = [
            c for c in broadcaster.send_message.call_args_list
            if "reply_to_message_id" not in c.kwargs
        ]
        wipe_found = any(
            "ill prepared" in c.kwargs.get("message", "").lower()
            for c in broadcast_calls
        )
        assert wipe_found


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("_dungeon_env")
class TestDungeonLevelSelection:
    async def test_three_players_unlocks_tonberry_cove(self, channel, _dungeon_env):
        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        broadcaster = MockBroadcaster(id=99999)

        with patch(
            "bot.skills.dungeon.transact_wallets",
            new_callable=AsyncMock,
            return_value=_transact_success(),
        ), patch(
            "bot.skills.dungeon.random.randint",
            return_value=1,
        ):
            for i in range(3):
                payload = MockPayload(
                    text="!dungeon 100",
                    chatter=MockChatter(name=f"p{i}", display_name=f"P{i}", id=3000 + i),
                    broadcaster=broadcaster,
                )
                await handler.handle(payload, "100", skill, bot)

            game = handler._games.get("99999")
            _dungeon_env.set()
            if game and game.task:
                await game.task

        # Check that entry_closed message mentions Tonberry Cove
        broadcast_calls = [
            c for c in broadcaster.send_message.call_args_list
            if "reply_to_message_id" not in c.kwargs
        ]
        level_mentioned = any(
            "Tonberry Cove" in c.kwargs.get("message", "")
            for c in broadcast_calls
        )
        assert level_mentioned


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("_dungeon_env")
class TestDungeonRunningPhaseIgnored:
    async def test_running_phase_ignores_new_entries(self, channel):
        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        from bot.skills.dungeon import DungeonGame
        from bot.skills.dungeon import DungeonParticipant

        # Manually create a game in running phase
        game = DungeonGame(
            broadcaster_id="99999",
            channel_name="testchannel",
            broadcaster=MockBroadcaster(id=99999),
            bot_id="00000",
            phase="running",
        )
        game.participants["111"] = DungeonParticipant(
            twitch_id="111", display_name="P1", username="p1", wager=100
        )
        handler._games["99999"] = game

        payload = MockPayload(
            text="!dungeon 500",
            broadcaster=MockBroadcaster(id=99999),
        )

        with patch(
            "bot.skills.dungeon.transact_wallets",
            new_callable=AsyncMock,
        ) as mock_transact:
            await handler.handle(payload, "500", skill, bot)
            mock_transact.assert_not_called()

        # No message sent (silently ignored)
        payload.broadcaster.send_message.assert_not_called()


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("_dungeon_env")
class TestDungeonWagerJournal:
    async def test_entry_journals_pending_wager(self, channel):
        from core.models import DungeonWager

        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        payload = MockPayload(
            text="!dungeon 500", broadcaster=MockBroadcaster(id=99999)
        )
        with patch(
            "bot.skills.dungeon.transact_wallets",
            new_callable=AsyncMock,
            return_value=_transact_success(),
        ):
            await handler.handle(payload, "500", skill, bot)
            game = handler._games["99999"]
            wager = DungeonWager.objects.get(game_key=game.game_key)
            assert wager.status == "pending"
            assert wager.wager == 500
            assert wager.channel_id == channel.id

    async def test_solo_loss_marks_wager_lost(self, channel, _dungeon_env):
        from core.models import DungeonWager

        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        payload = MockPayload(
            text="!dungeon 100", broadcaster=MockBroadcaster(id=99999)
        )
        with patch(
            "bot.skills.dungeon.transact_wallets",
            new_callable=AsyncMock,
            return_value=_transact_success(),
        ), patch("bot.skills.dungeon.random.randint", return_value=100):
            await handler.handle(payload, "100", skill, bot)
            game = handler._games.get("99999")
            game_key = game.game_key
            _dungeon_env.set()
            if game and game.task:
                await game.task

        wager = DungeonWager.objects.get(game_key=game_key)
        assert wager.status == "lost"
        assert wager.resolved_at is not None

    async def test_solo_win_marks_wager_won_with_payout(self, channel, _dungeon_env):
        from core.models import DungeonWager

        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        payload = MockPayload(
            text="!dungeon 100", broadcaster=MockBroadcaster(id=99999)
        )
        with patch(
            "bot.skills.dungeon.transact_wallets",
            new_callable=AsyncMock,
            return_value=_transact_success(),
        ), patch("bot.skills.dungeon.random.randint", return_value=1):
            await handler.handle(payload, "100", skill, bot)
            game = handler._games.get("99999")
            game_key = game.game_key
            _dungeon_env.set()
            if game and game.task:
                await game.task

        wager = DungeonWager.objects.get(game_key=game_key)
        assert wager.status == "won"
        assert wager.payout == 150  # 100 x 1.5 (Cactuar Village)

    async def test_payout_failure_leaves_wager_pending(self, channel, _dungeon_env):
        from core.models import DungeonWager

        skill = _make_skill(channel)
        handler = SKILL_REGISTRY["dungeon"]
        bot = MagicMock()
        bot.bot_id = "00000"

        payload = MockPayload(
            text="!dungeon 100", broadcaster=MockBroadcaster(id=99999)
        )
        # First transact (debit) succeeds; second (payout) fails.
        with patch(
            "bot.skills.dungeon.transact_wallets",
            new_callable=AsyncMock,
            side_effect=[_transact_success(), None],
        ), patch("bot.skills.dungeon.random.randint", return_value=1):
            await handler.handle(payload, "100", skill, bot)
            game = handler._games.get("99999")
            game_key = game.game_key
            _dungeon_env.set()
            if game and game.task:
                await game.task

        wager = DungeonWager.objects.get(game_key=game_key)
        assert wager.status == "pending"  # recovery refunds it next restart


@pytest.mark.django_db(transaction=True)
class TestDungeonRecovery:
    def _make_component(self, bot_twitch_id="66977097"):
        from datetime import timedelta

        from django.utils import timezone

        from bot.components.dungeonrecovery import DungeonRecovery

        bot = MagicMock()
        bot.bot_id = bot_twitch_id
        broadcaster = MagicMock()
        broadcaster.send_message = AsyncMock()
        bot.create_partialuser.return_value = broadcaster
        component = DungeonRecovery(bot)
        # Orphans predate the process; push the cutoff forward so rows
        # created inside the test count as "before startup".
        component._cutoff = timezone.now() + timedelta(seconds=5)
        return component, broadcaster

    def _pending_wager(self, channel, twitch_id="111", name="P1", amount=500):
        from core.models import DungeonWager

        return DungeonWager.objects.create(
            channel=channel,
            game_key="deadgame",
            twitch_id=twitch_id,
            twitch_username=name.lower(),
            display_name=name,
            wager=amount,
        )

    async def test_refunds_pending_wagers_and_announces(self, channel):

        w1 = self._pending_wager(channel, "111", "P1", 500)
        w2 = self._pending_wager(channel, "222", "P2", 200)
        component, broadcaster = self._make_component()

        with patch(
            "bot.components.dungeonrecovery.transact_wallets",
            new_callable=AsyncMock,
            return_value={"processed": 2, "failed": []},
        ) as mock_transact:
            await component._recover_channel(channel)

        entries = mock_transact.call_args[0][1]
        assert {e["twitch_id"]: e["amount"] for e in entries} == {
            "111": "500",
            "222": "200",
        }
        assert mock_transact.call_args.kwargs["reason"] == "dungeon_refund"

        w1.refresh_from_db()
        w2.refresh_from_db()
        assert w1.status == "refunded"
        assert w2.status == "refunded"

        msg = broadcaster.send_message.call_args.kwargs["message"]
        assert "refund" in msg.lower() or "wagers" in msg.lower()
        assert "P1 (500)" in msg

    async def test_failed_entry_stays_pending(self, channel):
        w1 = self._pending_wager(channel, "111", "P1", 500)
        w2 = self._pending_wager(channel, "222", "P2", 200)
        component, _ = self._make_component()

        with patch(
            "bot.components.dungeonrecovery.transact_wallets",
            new_callable=AsyncMock,
            return_value={
                "processed": 1,
                "failed": [{"twitch_id": "222", "error": "not_found"}],
            },
        ):
            await component._recover_channel(channel)

        w1.refresh_from_db()
        w2.refresh_from_db()
        assert w1.status == "refunded"
        assert w2.status == "pending"  # retried at next restart

    async def test_transact_failure_leaves_all_pending(self, channel):
        w1 = self._pending_wager(channel, "111", "P1", 500)
        component, broadcaster = self._make_component()

        with patch(
            "bot.components.dungeonrecovery.transact_wallets",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await component._recover_channel(channel)

        w1.refresh_from_db()
        assert w1.status == "pending"
        broadcaster.send_message.assert_not_called()

    async def test_ignores_wagers_created_after_startup(self, channel):
        from django.utils import timezone

        w1 = self._pending_wager(channel, "111", "P1", 500)
        component, _ = self._make_component()
        # Simulate a wager placed by a game that started after this process.
        component._cutoff = timezone.now() - timezone.timedelta(minutes=5)

        with patch(
            "bot.components.dungeonrecovery.transact_wallets",
            new_callable=AsyncMock,
        ) as mock_transact:
            await component._recover_channel(channel)

        mock_transact.assert_not_called()
        w1.refresh_from_db()
        assert w1.status == "pending"

    async def test_no_pending_wagers_is_quiet(self, channel):
        component, broadcaster = self._make_component()

        with patch(
            "bot.components.dungeonrecovery.transact_wallets",
            new_callable=AsyncMock,
        ) as mock_transact:
            await component._recover_channel(channel)

        mock_transact.assert_not_called()
        broadcaster.send_message.assert_not_called()
