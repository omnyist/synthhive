from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from bot.skills import SKILL_REGISTRY
from bot.skills import discover_skills
from bot.skills.give import GiveHandler
from tests.conftest import MockChatter
from tests.conftest import MockPayload


class TestGiveRegistry:
    def test_give_in_registry(self):
        discover_skills()
        assert "give" in SKILL_REGISTRY
        assert isinstance(SKILL_REGISTRY["give"], GiveHandler)


def _mock_bot():
    bot = MagicMock()
    bot.bot_id = "00000"
    return bot


def _mock_skill(channel_name="spoonee"):
    skill = MagicMock()
    skill.channel.twitch_channel_name = channel_name
    skill.config = {}
    return skill


def _mock_target(name="kefka", display_name="Kefka", user_id=55555):
    user = MagicMock()
    user.id = user_id
    user.name = name
    user.display_name = display_name
    return user


class TestGiveHandler:
    @pytest.fixture()
    def handler(self):
        return GiveHandler()

    @pytest.mark.asyncio
    @patch("bot.skills.give.transact_wallets")
    @patch("bot.skills.give.get_wallet")
    async def test_successful_transfer(
        self, mock_wallet, mock_transact, handler
    ):
        mock_wallet.return_value = {"currency_name": "spoons"}
        mock_transact.return_value = {"processed": 2, "failed": []}

        bot = _mock_bot()
        target = _mock_target()
        bot.fetch_users = AsyncMock(return_value=[target])

        payload = MockPayload(text="!give @kefka 100")
        await handler.handle(payload, "@kefka 100", _mock_skill(), bot)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "100 spoons" in msg
        assert "TestUser" in msg
        assert "Kefka" in msg
        assert msg.startswith("/me")

    @pytest.mark.asyncio
    @patch("bot.skills.give.transact_wallets")
    @patch("bot.skills.give.get_wallet")
    async def test_formatted_amount(self, mock_wallet, mock_transact, handler):
        mock_wallet.return_value = {"currency_name": "spoons"}
        mock_transact.return_value = {"processed": 2, "failed": []}

        bot = _mock_bot()
        bot.fetch_users = AsyncMock(return_value=[_mock_target()])

        payload = MockPayload(text="!give @kefka 10000")
        await handler.handle(payload, "@kefka 10000", _mock_skill(), bot)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "10,000" in msg

    @pytest.mark.asyncio
    async def test_missing_args(self, handler):
        bot = _mock_bot()
        payload = MockPayload(text="!give")
        await handler.handle(payload, "", _mock_skill(), bot)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "Usage" in msg

    @pytest.mark.asyncio
    async def test_missing_amount(self, handler):
        bot = _mock_bot()
        payload = MockPayload(text="!give @kefka")
        await handler.handle(payload, "@kefka", _mock_skill(), bot)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "Usage" in msg

    @pytest.mark.asyncio
    async def test_invalid_amount(self, handler):
        bot = _mock_bot()
        payload = MockPayload(text="!give @kefka abc")
        await handler.handle(payload, "@kefka abc", _mock_skill(), bot)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "whole number" in msg.lower()

    @pytest.mark.asyncio
    async def test_zero_amount(self, handler):
        bot = _mock_bot()
        payload = MockPayload(text="!give @kefka 0")
        await handler.handle(payload, "@kefka 0", _mock_skill(), bot)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "positive" in msg

    @pytest.mark.asyncio
    async def test_negative_amount(self, handler):
        bot = _mock_bot()
        payload = MockPayload(text="!give @kefka -50")
        await handler.handle(payload, "@kefka -50", _mock_skill(), bot)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "positive" in msg.lower()

    @pytest.mark.asyncio
    async def test_self_transfer_blocked(self, handler):
        bot = _mock_bot()
        payload = MockPayload(
            chatter=MockChatter(name="testuser"),
            text="!give @testuser 100",
        )
        await handler.handle(payload, "@testuser 100", _mock_skill(), bot)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "yourself" in msg.lower()

    @pytest.mark.asyncio
    async def test_unknown_target(self, handler):
        bot = _mock_bot()
        bot.fetch_users = AsyncMock(return_value=[])

        payload = MockPayload(text="!give @nobody 100")
        await handler.handle(payload, "@nobody 100", _mock_skill(), bot)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "don't know who" in msg.lower()

    @pytest.mark.asyncio
    @patch("bot.skills.give.transact_wallets")
    @patch("bot.skills.give.get_wallet")
    async def test_insufficient_funds(
        self, mock_wallet, mock_transact, handler
    ):
        mock_wallet.return_value = {"currency_name": "spoons"}
        mock_transact.return_value = {
            "processed": 0,
            "failed": [{"twitch_id": "12345", "error": "insufficient_funds"}],
        }

        bot = _mock_bot()
        bot.fetch_users = AsyncMock(return_value=[_mock_target()])

        payload = MockPayload(text="!give @kefka 999999")
        await handler.handle(payload, "@kefka 999999", _mock_skill(), bot)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "enough" in msg.lower()

    @pytest.mark.asyncio
    @patch("bot.skills.give.transact_wallets")
    @patch("bot.skills.give.get_wallet")
    async def test_api_failure(self, mock_wallet, mock_transact, handler):
        mock_wallet.return_value = {"currency_name": "spoons"}
        mock_transact.return_value = None

        bot = _mock_bot()
        bot.fetch_users = AsyncMock(return_value=[_mock_target()])

        payload = MockPayload(text="!give @kefka 100")
        await handler.handle(payload, "@kefka 100", _mock_skill(), bot)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "failed" in msg.lower()

    @pytest.mark.asyncio
    @patch("bot.skills.give.transact_wallets")
    @patch("bot.skills.give.get_wallet")
    async def test_transact_entries(self, mock_wallet, mock_transact, handler):
        """Verify the debit/credit entries sent to transact_wallets."""
        mock_wallet.return_value = {"currency_name": "spoons"}
        mock_transact.return_value = {"processed": 2, "failed": []}

        bot = _mock_bot()
        target = _mock_target()
        bot.fetch_users = AsyncMock(return_value=[target])

        payload = MockPayload(text="!give @kefka 250")
        await handler.handle(payload, "@kefka 250", _mock_skill(), bot)

        call_args = mock_transact.call_args
        entries = call_args.args[1]
        assert len(entries) == 2
        assert entries[0]["amount"] == "-250"
        assert entries[1]["amount"] == "250"
        assert call_args.kwargs["reason"] == "give"

    @pytest.mark.asyncio
    @patch("bot.skills.give.transact_wallets")
    @patch("bot.skills.give.get_wallet")
    async def test_no_wallet_defaults_to_points(
        self, mock_wallet, mock_transact, handler
    ):
        mock_wallet.return_value = None
        mock_transact.return_value = {"processed": 2, "failed": []}

        bot = _mock_bot()
        bot.fetch_users = AsyncMock(return_value=[_mock_target()])

        payload = MockPayload(text="!give @kefka 100")
        await handler.handle(payload, "@kefka 100", _mock_skill(), bot)

        msg = payload.broadcaster.send_message.call_args.kwargs["message"]
        assert "points" in msg
