"""Tests for the lizardroulette mood engine."""

from __future__ import annotations

from collections import deque
from unittest.mock import patch

import pytest

from bot.skills.lizardmood import BASE_WEIGHTS
from bot.skills.lizardmood import DEATH_TIER_RANGES
from bot.skills.lizardmood import MOOD_BEHAVIORS
from bot.skills.lizardmood import MOOD_DEATH
from bot.skills.lizardmood import MOOD_SURVIVAL
from bot.skills.lizardmood import SURVIVAL_TIER_RANGES
from bot.skills.lizardmood import Mood
from bot.skills.lizardmood import MoodContext
from bot.skills.lizardmood import RecencyTracker
from bot.skills.lizardmood import DeathMessage
from bot.skills.lizardmood import _get_tier_key
from bot.skills.lizardmood import _ordinal
from bot.skills.lizardmood import recency
from bot.skills.lizardmood import render_death
from bot.skills.lizardmood import render_survival
from bot.skills.lizardmood import roll_mood


def _render_death_text(mood: Mood, ctx: MoodContext) -> str:
    """Helper: render death and return just the text."""
    return render_death(mood, ctx).text


def _make_ctx(**overrides) -> MoodContext:
    """Create a MoodContext with sensible defaults, overriding as needed."""
    defaults = {
        "outcome": "death",
        "deaths": 1,
        "streak": 0,
        "max_streak": 0,
        "chatter_name": "TestUser",
        "victim": "",
        "is_self_victim": False,
        "bullets_loaded": False,
        "chemical": "dopamine",
    }
    defaults.update(overrides)
    return MoodContext(**defaults)


# ---------------------------------------------------------------------------
# Weight computation
# ---------------------------------------------------------------------------


class TestWeightAdjusters:
    def test_high_death_count_boosts_bored_and_clinical(self):
        ctx = _make_ctx(deaths=150)
        roll = roll_mood(ctx)
        assert roll.weights[Mood.BORED] > BASE_WEIGHTS[Mood.BORED]
        assert roll.weights[Mood.CLINICAL] > BASE_WEIGHTS[Mood.CLINICAL]

    def test_high_death_count_reduces_theatrical(self):
        ctx = _make_ctx(deaths=150)
        roll = roll_mood(ctx)
        assert roll.weights[Mood.THEATRICAL] < BASE_WEIGHTS[Mood.THEATRICAL]

    def test_medium_death_count_boosts_bored(self):
        ctx = _make_ctx(deaths=60)
        roll = roll_mood(ctx)
        assert roll.weights[Mood.BORED] > BASE_WEIGHTS[Mood.BORED]

    def test_low_death_count_unchanged(self):
        ctx = _make_ctx(deaths=5)
        roll = roll_mood(ctx)
        assert roll.weights[Mood.BORED] == BASE_WEIGHTS[Mood.BORED]

    def test_high_survival_streak_boosts_impressed(self):
        ctx = _make_ctx(outcome="survival", streak=10, deaths=0)
        roll = roll_mood(ctx)
        assert roll.weights[Mood.IMPRESSED] > BASE_WEIGHTS[Mood.IMPRESSED]

    def test_broken_high_streak_boosts_gleeful(self):
        ctx = _make_ctx(outcome="death", streak=8, deaths=5)
        roll = roll_mood(ctx)
        assert roll.weights[Mood.GLEEFUL] > BASE_WEIGHTS[Mood.GLEEFUL]

    def test_bullets_loaded_boosts_smug(self):
        ctx = _make_ctx(bullets_loaded=True)
        roll = roll_mood(ctx)
        assert roll.weights[Mood.SMUG] > BASE_WEIGHTS[Mood.SMUG]

    def test_first_death_zeroes_bored(self):
        ctx = _make_ctx(deaths=1)
        roll = roll_mood(ctx)
        assert roll.weights[Mood.BORED] == 0

    def test_first_death_boosts_theatrical(self):
        ctx = _make_ctx(deaths=1)
        roll = roll_mood(ctx)
        assert roll.weights[Mood.THEATRICAL] > BASE_WEIGHTS[Mood.THEATRICAL]

    def test_all_weights_non_negative(self):
        ctx = _make_ctx(deaths=200, streak=0)
        roll = roll_mood(ctx)
        for weight in roll.weights.values():
            assert weight >= 0


# ---------------------------------------------------------------------------
# Scripting detection
# ---------------------------------------------------------------------------


class TestScriptingDetection:
    def test_scripted_boosts_suspicious(self):
        ctx = _make_ctx(is_scripted=True)
        roll = roll_mood(ctx)
        assert roll.weights[Mood.SUSPICIOUS] > 0

    def test_not_scripted_keeps_suspicious_at_zero(self):
        ctx = _make_ctx(is_scripted=False)
        roll = roll_mood(ctx)
        assert roll.weights[Mood.SUSPICIOUS] == 0

    def test_suspicious_death_has_no_countdown(self):
        ctx = _make_ctx(deaths=50, chatter_name="akk", is_scripted=True)
        with patch("bot.skills.lizardmood.random.random", return_value=1.0):
            result = render_death(Mood.SUSPICIOUS, ctx)
        assert "3, 2, 1" not in result.text
        assert "THREE" not in result.text

    def test_suspicious_death_is_timeout_first(self):
        ctx = _make_ctx(deaths=50, chatter_name="akk", is_scripted=True)
        with patch("bot.skills.lizardmood.random.random", return_value=1.0):
            result = render_death(Mood.SUSPICIOUS, ctx)
        assert result.timeout_first is True

    def test_suspicious_survival_references_timing(self):
        ctx = _make_ctx(
            outcome="survival", streak=3, chatter_name="akk", is_scripted=True,
        )
        with patch("bot.skills.lizardmood.random.random", return_value=1.0):
            msg = render_survival(Mood.SUSPICIOUS, ctx)
        assert "akk" in msg
        assert "bardLizard" in msg

    def test_handler_detects_consistent_intervals(self):
        from bot.skills.lizardroulette import LizardRouletteHandler

        handler = LizardRouletteHandler()
        key = "99999:12345"
        handler._play_intervals[key] = deque([1800, 1805, 1798], maxlen=3)
        assert handler._detect_scripted(key) is True

    def test_handler_no_detection_with_varied_intervals(self):
        from bot.skills.lizardroulette import LizardRouletteHandler

        handler = LizardRouletteHandler()
        key = "99999:12345"
        handler._play_intervals[key] = deque([1800, 2400, 1200], maxlen=3)
        assert handler._detect_scripted(key) is False

    def test_handler_no_detection_with_insufficient_data(self):
        from bot.skills.lizardroulette import LizardRouletteHandler

        handler = LizardRouletteHandler()
        key = "99999:12345"
        handler._play_intervals[key] = deque([1800], maxlen=3)
        assert handler._detect_scripted(key) is False


# ---------------------------------------------------------------------------
# Mood roll
# ---------------------------------------------------------------------------


class TestRollMood:
    def test_returns_mood_roll_with_context(self):
        ctx = _make_ctx()
        roll = roll_mood(ctx)
        assert roll.ctx is ctx
        assert isinstance(roll.mood, Mood)
        assert isinstance(roll.weights, dict)

    def test_deterministic_with_mocked_random(self):
        ctx = _make_ctx()
        with patch(
            "bot.skills.lizardmood.random.choices",
            return_value=[Mood.DEADPAN],
        ):
            roll = roll_mood(ctx)
        assert roll.mood == Mood.DEADPAN

    def test_weight_fn_override(self):
        ctx = _make_ctx()

        def force_clinical(weights, _ctx):
            return {m: (100 if m == Mood.CLINICAL else 0) for m in Mood}

        with patch(
            "bot.skills.lizardmood.random.choices",
            side_effect=lambda moods, weights, k: [
                moods[weights.index(max(weights))]
            ],
        ):
            roll = roll_mood(ctx, weight_fn=force_clinical)
        assert roll.mood == Mood.CLINICAL

    def test_all_zero_weights_falls_back_to_theatrical(self):
        ctx = _make_ctx()

        def zero_all(weights, _ctx):
            return {m: 0 for m in Mood}

        roll = roll_mood(ctx, weight_fn=zero_all)
        assert roll.mood == Mood.THEATRICAL


# ---------------------------------------------------------------------------
# Tier selection
# ---------------------------------------------------------------------------


class TestGetTierKey:
    def test_survival_tier_1(self):
        assert _get_tier_key(SURVIVAL_TIER_RANGES, 1) == (1, 2)

    def test_survival_tier_2(self):
        assert _get_tier_key(SURVIVAL_TIER_RANGES, 3) == (3, 4)

    def test_survival_tier_3(self):
        assert _get_tier_key(SURVIVAL_TIER_RANGES, 5) == (5, 7)

    def test_survival_tier_4(self):
        assert _get_tier_key(SURVIVAL_TIER_RANGES, 10) == (8, None)

    def test_survival_tier_extreme(self):
        assert _get_tier_key(SURVIVAL_TIER_RANGES, 100) == (8, None)

    def test_death_tier_first(self):
        assert _get_tier_key(DEATH_TIER_RANGES, 1) == (1, 1)

    def test_death_tier_early(self):
        assert _get_tier_key(DEATH_TIER_RANGES, 5) == (2, 9)

    def test_death_tier_mid(self):
        assert _get_tier_key(DEATH_TIER_RANGES, 15) == (10, 24)

    def test_death_tier_high(self):
        assert _get_tier_key(DEATH_TIER_RANGES, 30) == (25, 49)

    def test_death_tier_very_high(self):
        assert _get_tier_key(DEATH_TIER_RANGES, 70) == (50, 99)

    def test_death_tier_extreme(self):
        assert _get_tier_key(DEATH_TIER_RANGES, 100) == (100, None)


# ---------------------------------------------------------------------------
# Rendering — death messages
# ---------------------------------------------------------------------------


class TestRenderDeath:
    def test_theatrical_has_countdown(self):
        ctx = _make_ctx(deaths=5, chatter_name="akk")
        msg = _render_death_text(Mood.THEATRICAL, ctx)
        assert "3, 2, 1..." in msg
        assert "akk" in msg
        assert "LizardWithAGun" in msg

    def test_bored_has_no_countdown(self):
        ctx = _make_ctx(deaths=50, chatter_name="akk")
        msg = _render_death_text(Mood.BORED, ctx)
        assert "3, 2, 1" not in msg
        assert "THREE" not in msg
        assert "LizardWithAGun" in msg

    def test_impressed_has_slow_countdown(self):
        ctx = _make_ctx(deaths=1, chatter_name="test")
        msg = _render_death_text(Mood.IMPRESSED, ctx)
        assert "3... 2... 1..." in msg

    def test_smug_has_standard_countdown(self):
        ctx = _make_ctx(deaths=10, chatter_name="test")
        msg = _render_death_text(Mood.SMUG, ctx)
        assert "3, 2, 1..." in msg

    def test_clinical_has_commencing(self):
        ctx = _make_ctx(deaths=100, chatter_name="subject")
        msg = _render_death_text(Mood.CLINICAL, ctx)
        assert "Timeout commencing." in msg

    def test_gleeful_has_caps_countdown(self):
        ctx = _make_ctx(deaths=5, streak=8, chatter_name="test")
        msg = _render_death_text(Mood.GLEEFUL, ctx)
        assert "THREE! TWO! ONE!" in msg

    def test_deadpan_has_no_countdown(self):
        ctx = _make_ctx(deaths=50, chatter_name="test")
        msg = _render_death_text(Mood.DEADPAN, ctx)
        assert "3, 2, 1" not in msg
        assert "THREE" not in msg

    def test_substitutes_deaths_ordinal(self):
        ctx = _make_ctx(deaths=3, chatter_name="test")
        msg = _render_death_text(Mood.THEATRICAL, ctx)
        if "$(deaths)" not in msg:
            pass
        assert "$(deaths)" not in msg

    def test_substitutes_raw_deaths(self):
        ctx = _make_ctx(deaths=42, chatter_name="test")
        msg = _render_death_text(Mood.CLINICAL, ctx)
        assert "42" in msg

    def test_substitutes_user(self):
        ctx = _make_ctx(deaths=1, chatter_name="CoolPlayer")
        msg = _render_death_text(Mood.THEATRICAL, ctx)
        assert "CoolPlayer" in msg


# ---------------------------------------------------------------------------
# Rendering — survival messages
# ---------------------------------------------------------------------------


class TestRenderSurvival:
    def test_theatrical_includes_victim_clause(self):
        ctx = _make_ctx(
            outcome="survival",
            streak=1,
            chatter_name="winner",
            victim="loser",
        )
        msg = render_survival(Mood.THEATRICAL, ctx)
        assert "loser" in msg
        assert "bardLizard" in msg

    def test_bored_excludes_victim_clause(self):
        ctx = _make_ctx(
            outcome="survival",
            streak=1,
            chatter_name="winner",
            victim="loser",
        )
        msg = render_survival(Mood.BORED, ctx)
        assert "loser" not in msg

    def test_deadpan_excludes_victim_clause(self):
        ctx = _make_ctx(
            outcome="survival",
            streak=1,
            chatter_name="winner",
            victim="loser",
        )
        msg = render_survival(Mood.DEADPAN, ctx)
        assert "loser" not in msg

    def test_clinical_excludes_victim_clause(self):
        ctx = _make_ctx(
            outcome="survival",
            streak=1,
            chatter_name="winner",
            victim="loser",
        )
        msg = render_survival(Mood.CLINICAL, ctx)
        assert "loser" not in msg

    def test_impressed_includes_victim_clause(self):
        ctx = _make_ctx(
            outcome="survival",
            streak=1,
            chatter_name="winner",
            victim="loser",
        )
        msg = render_survival(Mood.IMPRESSED, ctx)
        assert "loser" in msg

    def test_self_victim_clause(self):
        ctx = _make_ctx(
            outcome="survival",
            streak=1,
            chatter_name="SameUser",
            victim="SameUser",
            is_self_victim=True,
        )
        msg = render_survival(Mood.THEATRICAL, ctx)
        assert "bardLizard" in msg
        assert "SameUser" in msg

    def test_no_victim_no_clause(self):
        ctx = _make_ctx(
            outcome="survival",
            streak=1,
            chatter_name="test",
            victim="",
        )
        msg = render_survival(Mood.THEATRICAL, ctx)
        assert "bardLizard" in msg

    def test_substitutes_chemical(self):
        ctx = _make_ctx(
            outcome="survival",
            streak=1,
            chatter_name="test",
            chemical="serotonin",
        )
        msg = render_survival(Mood.THEATRICAL, ctx)
        if "$(chemical)" in msg:
            pytest.fail("Chemical variable not substituted")

    def test_substitutes_streak(self):
        ctx = _make_ctx(
            outcome="survival",
            streak=5,
            chatter_name="test",
        )
        msg = render_survival(Mood.THEATRICAL, ctx)
        assert "5" in msg

    def test_always_ends_with_emote(self):
        with patch("bot.skills.lizardmood.random.random", return_value=1.0):
            for mood in Mood:
                ctx = _make_ctx(outcome="survival", streak=1, chatter_name="test")
                msg = render_survival(mood, ctx)
                assert msg.endswith("bardLizard"), f"{mood.value} missing bardLizard"


# ---------------------------------------------------------------------------
# Rare messages
# ---------------------------------------------------------------------------


class TestRareMessages:
    def test_rare_death_fires_when_rolled(self):
        ctx = _make_ctx(deaths=5, chatter_name="akk")
        with patch("bot.skills.lizardmood.random.random", return_value=0.01):
            msg = _render_death_text(Mood.THEATRICAL, ctx)
        assert "bardGun" in msg or "bardA" in msg
        assert "LizardWithAGun" not in msg

    def test_rare_death_skipped_on_high_roll(self):
        ctx = _make_ctx(deaths=5, chatter_name="akk")
        with patch("bot.skills.lizardmood.random.random", return_value=0.5):
            msg = _render_death_text(Mood.THEATRICAL, ctx)
        assert "LizardWithAGun" in msg

    def test_rare_uses_custom_emote(self):
        ctx = _make_ctx(deaths=5, chatter_name="TestUser")
        with patch("bot.skills.lizardmood.random.random", return_value=0.01):
            msg = _render_death_text(Mood.THEATRICAL, ctx)
        assert "bardGun" in msg or "bardA" in msg

    def test_rare_substitutes_variables(self):
        ctx = _make_ctx(deaths=5, chatter_name="CoolPlayer")
        with patch("bot.skills.lizardmood.random.random", return_value=0.01):
            msg = _render_death_text(Mood.THEATRICAL, ctx)
        assert "CoolPlayer" in msg

    def test_no_rare_pool_never_fires(self):
        ctx = _make_ctx(deaths=5, chatter_name="test")
        with patch("bot.skills.lizardmood.random.random", return_value=0.01):
            msg = _render_death_text(Mood.BORED, ctx)
        assert "LizardWithAGun" in msg

    def test_rare_no_countdown(self):
        ctx = _make_ctx(deaths=5, chatter_name="test")
        with patch("bot.skills.lizardmood.random.random", return_value=0.01):
            msg = _render_death_text(Mood.THEATRICAL, ctx)
        assert "3, 2, 1" not in msg

    def test_timeout_first_rare(self):
        ctx = _make_ctx(deaths=75, chatter_name="akk")
        with patch("bot.skills.lizardmood.random.random", return_value=0.01):
            result = render_death(Mood.BORED, ctx)
        assert isinstance(result, DeathMessage)
        assert result.timeout_first is True
        assert "akk" in result.text

    def test_normal_death_not_timeout_first(self):
        ctx = _make_ctx(deaths=5, chatter_name="test")
        with patch("bot.skills.lizardmood.random.random", return_value=1.0):
            result = render_death(Mood.THEATRICAL, ctx)
        assert result.timeout_first is False


# ---------------------------------------------------------------------------
# Recency tracker
# ---------------------------------------------------------------------------


class TestRecencyTracker:
    def setup_method(self):
        recency.clear()

    def test_avoids_recent_pick(self):
        tracker = RecencyTracker()
        options = ["A", "B", "C"]
        first = tracker.pick("ch1", options)
        second = tracker.pick("ch1", options)
        assert second != first
        third = tracker.pick("ch1", options)
        assert third != second

    def test_falls_back_when_all_recent(self):
        tracker = RecencyTracker()
        options = ["A"]
        first = tracker.pick("ch1", options)
        assert first == "A"
        second = tracker.pick("ch1", options)
        assert second == "A"

    def test_channels_are_independent(self):
        tracker = RecencyTracker()
        tracker.pick("ch1", ["A"])
        result = tracker.pick("ch2", ["A", "B"])
        assert result in ("A", "B")

    def test_clear_channel(self):
        tracker = RecencyTracker()
        tracker.pick("ch1", ["A"])
        tracker.clear("ch1")
        result = tracker.pick("ch1", ["A", "B"])
        assert result in ("A", "B")

    def test_clear_all(self):
        tracker = RecencyTracker()
        tracker.pick("ch1", ["A"])
        tracker.pick("ch2", ["X"])
        tracker.clear()
        r1 = tracker.pick("ch1", ["A", "B"])
        r2 = tracker.pick("ch2", ["X", "Y"])
        assert r1 in ("A", "B")
        assert r2 in ("X", "Y")

    def test_flow_produces_connected_body_and_clause(self):
        recency.clear()
        ctx = _make_ctx(
            outcome="survival",
            streak=6,
            chatter_name="TestUser",
            victim="DeadPlayer",
            channel_id="99999",
        )
        with (
            patch("bot.skills.lizardmood.random.random", side_effect=[1.0, 0.1]),
            patch("bot.skills.lizardmood.FLOW_CHANCE", 1.0),
        ):
            msg = render_survival(Mood.THEATRICAL, ctx)
        assert "TestUser" in msg
        assert "DeadPlayer" in msg or "TestUser" in msg
        assert "bardLizard" in msg

    def test_flow_not_used_without_victim(self):
        recency.clear()
        ctx = _make_ctx(
            outcome="survival",
            streak=6,
            chatter_name="TestUser",
            victim="",
            channel_id="99999",
        )
        with patch("bot.skills.lizardmood.FLOW_CHANCE", 1.0):
            msg = render_survival(Mood.THEATRICAL, ctx)
        assert "bardLizard" in msg

    def test_render_avoids_repeat_fragments(self):
        recency.clear()
        ctx = _make_ctx(
            outcome="survival",
            streak=1,
            chatter_name="test",
            channel_id="99999",
        )
        with patch("bot.skills.lizardmood.random.random", return_value=1.0):
            msg1 = render_survival(Mood.THEATRICAL, ctx)
            msg2 = render_survival(Mood.THEATRICAL, ctx)
        assert msg1 != msg2 or len(
            MOOD_SURVIVAL[Mood.THEATRICAL][(1, 2)]["openers"]
        ) == 1


# ---------------------------------------------------------------------------
# Pool completeness — every mood has every tier
# ---------------------------------------------------------------------------


class TestPoolCompleteness:
    def test_all_moods_have_all_survival_tiers(self):
        for mood in Mood:
            for tier in SURVIVAL_TIER_RANGES:
                assert tier in MOOD_SURVIVAL[mood], (
                    f"{mood.value} missing survival tier {tier}"
                )
                pool = MOOD_SURVIVAL[mood][tier]
                assert len(pool["openers"]) >= 2, (
                    f"{mood.value} survival {tier} needs more openers"
                )
                assert len(pool["bodies"]) >= 2, (
                    f"{mood.value} survival {tier} needs more bodies"
                )

    def test_all_moods_have_all_death_tiers(self):
        for mood in Mood:
            for tier in DEATH_TIER_RANGES:
                assert tier in MOOD_DEATH[mood], (
                    f"{mood.value} missing death tier {tier}"
                )
                pool = MOOD_DEATH[mood][tier]
                assert len(pool["cores"]) >= 2, (
                    f"{mood.value} death {tier} needs more cores"
                )

    def test_all_moods_have_behaviors(self):
        for mood in Mood:
            assert mood in MOOD_BEHAVIORS, f"{mood.value} missing behavior"

    def test_all_moods_have_base_weights(self):
        for mood in Mood:
            assert mood in BASE_WEIGHTS, f"{mood.value} missing base weight"

    def test_victim_clause_moods_have_clauses(self):
        for mood in Mood:
            behavior = MOOD_BEHAVIORS[mood]
            if behavior.include_victim_clause:
                for tier in SURVIVAL_TIER_RANGES:
                    pool = MOOD_SURVIVAL[mood][tier]
                    assert "victim_clauses" in pool, (
                        f"{mood.value} survival {tier} missing victim_clauses"
                    )
                    assert "self_victim_clauses" in pool, (
                        f"{mood.value} survival {tier} missing self_victim_clauses"
                    )


# ---------------------------------------------------------------------------
# Ordinal
# ---------------------------------------------------------------------------


class TestOrdinal:
    def test_basic_ordinals(self):
        assert _ordinal(1) == "1st"
        assert _ordinal(2) == "2nd"
        assert _ordinal(3) == "3rd"
        assert _ordinal(4) == "4th"

    def test_teens(self):
        assert _ordinal(11) == "11th"
        assert _ordinal(12) == "12th"
        assert _ordinal(13) == "13th"

    def test_larger_numbers(self):
        assert _ordinal(21) == "21st"
        assert _ordinal(22) == "22nd"
        assert _ordinal(100) == "100th"
        assert _ordinal(111) == "111th"
        assert _ordinal(112) == "112th"
        assert _ordinal(113) == "113th"
