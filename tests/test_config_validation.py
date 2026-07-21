"""Tests for skill/command config schema validation."""

from __future__ import annotations

from core.config_validation import skill_schemas
from core.config_validation import validate_command_config
from core.config_validation import validate_skill_config


class TestSkillConfigValidation:
    def test_valid_lizardroulette_config(self):
        config, error = validate_skill_config(
            "lizardroulette", {"odds": 25, "cooldown": 60}
        )
        assert error is None
        assert config == {"odds": 25, "cooldown": 60}

    def test_typo_key_rejected(self):
        _, error = validate_skill_config(
            "lizardroulette", {"cooldown_repsonse": "oops"}
        )
        assert error is not None
        assert "cooldown_repsonse" in error

    def test_odds_out_of_range(self):
        _, error = validate_skill_config("lizardroulette", {"odds": 101})
        assert error is not None
        assert "odds" in error

    def test_wrong_type_rejected(self):
        _, error = validate_skill_config(
            "lizardroulette", {"bullets_enabled": "sometimes"}
        )
        assert error is not None

    def test_sparse_dump_keeps_only_set_keys(self):
        config, error = validate_skill_config("lizardroulette", {"odds": 50})
        assert error is None
        assert config == {"odds": 50}  # defaults NOT copied into the row

    def test_dungeon_wager_bounds(self):
        _, error = validate_skill_config(
            "dungeon", {"min_wager": 500, "max_wager": 100}
        )
        assert error is not None
        assert "max_wager" in error

    def test_dungeon_unknown_message_key(self):
        _, error = validate_skill_config(
            "dungeon", {"messages": {"outcome_wpie": "typo"}}
        )
        assert error is not None
        assert "outcome_wpie" in error

    def test_dungeon_bad_level(self):
        _, error = validate_skill_config(
            "dungeon",
            {"levels": [{"name": "X", "min_players": 0, "survival_chance": 50, "multiplier": 1.5}]},
        )
        assert error is not None

    def test_dungeon_valid_full_config(self):
        config, error = validate_skill_config(
            "dungeon",
            {
                "currency_name": "spoons",
                "levels": [
                    {"name": "A", "min_players": 1, "survival_chance": 70, "multiplier": 1.5}
                ],
                "messages": {"entry_started": "go!"},
            },
        )
        assert error is None
        assert config["currency_name"] == "spoons"
        assert config["levels"][0]["name"] == "A"

    def test_ads_component_message_keys_allowed(self):
        config, error = validate_skill_config(
            "ads", {"messages": {"warning": "ad soon!", "status_off": "off"}}
        )
        assert error is None
        assert config["messages"]["warning"] == "ad soon!"

    def test_ads_unknown_message_key_rejected(self):
        _, error = validate_skill_config(
            "ads", {"messages": {"warnign": "typo"}}
        )
        assert error is not None

    def test_schema_less_skill_passes_through(self):
        config, error = validate_skill_config("markov", {"anything": True})
        assert error is None
        assert config == {"anything": True}

    def test_unknown_skill_passes_through(self):
        config, error = validate_skill_config("nonexistent", {"x": 1})
        assert error is None
        assert config == {"x": 1}


class TestSkillSchemas:
    def test_schemas_include_declared_and_none(self):
        schemas = skill_schemas()
        assert schemas["lizardroulette"] is not None
        assert "odds" in schemas["lizardroulette"]["properties"]
        assert schemas["markov"] is None

    def test_neutral_defaults_have_no_foreign_flavor(self):
        """Tenant #4's embarrassment check: no channel-specific emotes
        or currency in any schema default."""
        import json

        blob = json.dumps(skill_schemas())
        for marker in ("bard", "avalon", "spoons", "elsydeon"):
            assert marker not in blob, f"tenant flavor '{marker}' in schema defaults"


class TestCommandConfigValidation:
    def test_lottery_valid(self):
        config, error = validate_command_config(
            "lottery", {"odds": 10, "success": "yes", "failure": "no"}
        )
        assert error is None
        assert config["odds"] == 10

    def test_lottery_odds_bounds(self):
        _, error = validate_command_config("lottery", {"odds": 0})
        assert error is not None

    def test_random_list_valid(self):
        _, error = validate_command_config(
            "random_list", {"responses": ["a", "b"], "prefix": "🐚 "}
        )
        assert error is None

    def test_random_list_wrong_type(self):
        _, error = validate_command_config(
            "random_list", {"responses": "not-a-list"}
        )
        assert error is not None

    def test_text_rejects_unknown_keys(self):
        _, error = validate_command_config("text", {"resposnes": ["typo"]})
        assert error is not None

    def test_text_allows_cooldown_response(self):
        _, error = validate_command_config(
            "text", {"cooldown_response": "wait $(remaining)s"}
        )
        assert error is None

    def test_counter_valid(self):
        _, error = validate_command_config(
            "counter", {"counter_name": "death"}
        )
        assert error is None
