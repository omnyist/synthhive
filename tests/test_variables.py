from __future__ import annotations

import re

import pytest

from bot.variables import VARIABLE_PATTERN
from bot.variables import ChannelHandler
from bot.variables import CountHandler
from bot.variables import IndexHandler
from bot.variables import QueryHandler
from bot.variables import RandomHandler
from bot.variables import TargetHandler
from bot.variables import UserHandler
from bot.variables import UsesHandler
from bot.variables import VariableContext
from bot.variables import VariableRegistry
from bot.variables import create_registry


# --- Regex pattern tests ---


class TestVariablePattern:
    """Test the VARIABLE_PATTERN regex against all supported forms."""

    @pytest.mark.parametrize(
        "text, expected",
        [
            ("$(user)", ("user", None, None)),
            ("$(target)", ("target", None, None)),
            ("$(channel)", ("channel", None, None)),
            ("$(uses)", ("uses", None, None)),
            ("$(query)", ("query", None, None)),
            ("$(1)", ("1", None, None)),
            ("$(2)", ("2", None, None)),
            ("$(count.get death)", ("count", "get", "death")),
            ("$(count.label death)", ("count", "label", "death")),
            ("$(random.range 1-100)", ("random", "range", "1-100")),
            ("$(random.pick heads,tails)", ("random", "pick", "heads,tails")),
        ],
    )
    def test_pattern_matches(self, text, expected):
        match = VARIABLE_PATTERN.search(text)
        assert match is not None
        assert (match.group(1), match.group(2), match.group(3)) == expected

    def test_pattern_no_match_on_plain_text(self):
        assert VARIABLE_PATTERN.search("hello world") is None

    def test_pattern_multiple_variables_in_text(self):
        text = "Hello $(user), welcome to $(channel)!"
        matches = list(VARIABLE_PATTERN.finditer(text))
        assert len(matches) == 2
        assert matches[0].group(1) == "user"
        assert matches[1].group(1) == "channel"

    def test_pattern_nested_parentheses_ignored(self):
        # The pattern should not match $(count.get death) if parens are broken
        assert VARIABLE_PATTERN.search("$(") is None
        assert VARIABLE_PATTERN.search("$()") is None

    def test_pattern_with_surrounding_text(self):
        text = "You've used this command $(uses) times."
        match = VARIABLE_PATTERN.search(text)
        assert match is not None
        assert match.group(1) == "uses"

    def test_pattern_args_with_spaces(self):
        text = "$(random.pick red, blue, green)"
        match = VARIABLE_PATTERN.search(text)
        assert match is not None
        assert match.group(3) == "red, blue, green"


# --- Individual handler tests ---


class TestUserHandler:
    async def test_resolve(self, variable_context):
        handler = UserHandler()
        result = await handler.resolve(None, None, variable_context)
        assert result == "TestUser"

    def test_describe(self):
        handler = UserHandler()
        descriptors = handler.describe()
        assert len(descriptors) == 1
        assert descriptors[0].namespace == "user"
        assert descriptors[0].example == "$(user)"


class TestTargetHandler:
    async def test_resolve(self, variable_context):
        handler = TargetHandler()
        result = await handler.resolve(None, None, variable_context)
        assert result == "TargetUser"

    def test_describe(self):
        handler = TargetHandler()
        descriptors = handler.describe()
        assert len(descriptors) == 1
        assert descriptors[0].namespace == "target"


class TestChannelHandler:
    async def test_resolve(self, variable_context):
        handler = ChannelHandler()
        result = await handler.resolve(None, None, variable_context)
        assert result == "testchannel"


class TestUsesHandler:
    async def test_resolve(self, variable_context):
        handler = UsesHandler()
        result = await handler.resolve(None, None, variable_context)
        assert result == "42"

    async def test_resolve_zero(self, variable_context):
        variable_context.use_count = 0
        handler = UsesHandler()
        result = await handler.resolve(None, None, variable_context)
        assert result == "0"


class TestCountHandler:
    @pytest.mark.django_db(transaction=True)
    async def test_resolve_existing_counter(self, make_counter, variable_context):
        make_counter(name="death", value=7, label="Death Count")
        handler = CountHandler()
        result = await handler.resolve("get", "death", variable_context)
        assert result == "7"

    @pytest.mark.django_db(transaction=True)
    async def test_resolve_label(self, make_counter, variable_context):
        make_counter(name="death", value=7, label="Death Count")
        handler = CountHandler()
        result = await handler.resolve("label", "death", variable_context)
        assert result == "Death Count"

    @pytest.mark.django_db(transaction=True)
    async def test_resolve_label_falls_back_to_title(
        self, make_counter, variable_context
    ):
        make_counter(name="death", value=7, label="")
        handler = CountHandler()
        result = await handler.resolve("label", "death", variable_context)
        assert result == "Death"

    @pytest.mark.django_db(transaction=True)
    async def test_resolve_missing_counter(self, channel, variable_context):
        handler = CountHandler()
        result = await handler.resolve("get", "nonexistent", variable_context)
        assert result == "0"

    @pytest.mark.django_db(transaction=True)
    async def test_resolve_missing_counter_label(self, channel, variable_context):
        handler = CountHandler()
        result = await handler.resolve("label", "nonexistent", variable_context)
        assert result == "Nonexistent"

    async def test_resolve_no_prop_returns_literal(self, variable_context):
        handler = CountHandler()
        result = await handler.resolve(None, None, variable_context)
        assert result == "$(count)"

    async def test_resolve_no_args_returns_literal(self, variable_context):
        handler = CountHandler()
        result = await handler.resolve("get", None, variable_context)
        assert result == "$(count)"

    def test_describe(self):
        handler = CountHandler()
        descriptors = handler.describe()
        assert len(descriptors) == 2
        namespaces = {d.property for d in descriptors}
        assert "get" in namespaces
        assert "label" in namespaces


class TestRandomHandler:
    async def test_range(self, variable_context):
        handler = RandomHandler()
        result = await handler.resolve("range", "1-10", variable_context)
        value = int(result)
        assert 1 <= value <= 10

    async def test_range_single_value(self, variable_context):
        handler = RandomHandler()
        result = await handler.resolve("range", "5-5", variable_context)
        assert result == "5"

    async def test_range_invalid_returns_literal(self, variable_context):
        handler = RandomHandler()
        result = await handler.resolve("range", "abc", variable_context)
        assert result == "$(random.range)"

    async def test_pick(self, variable_context):
        handler = RandomHandler()
        result = await handler.resolve("pick", "heads,tails", variable_context)
        assert result in ("heads", "tails")

    async def test_pick_single_choice(self, variable_context):
        handler = RandomHandler()
        result = await handler.resolve("pick", "only", variable_context)
        assert result == "only"

    async def test_pick_empty_args_returns_literal(self, variable_context):
        handler = RandomHandler()
        # Empty string triggers the early `not args` check
        result = await handler.resolve("pick", "", variable_context)
        assert result == "$(random)"

    async def test_pick_whitespace_only_returns_literal(self, variable_context):
        handler = RandomHandler()
        result = await handler.resolve("pick", "  ,  , ", variable_context)
        assert result == "$(random.pick)"

    async def test_no_prop_returns_literal(self, variable_context):
        handler = RandomHandler()
        result = await handler.resolve(None, None, variable_context)
        assert result == "$(random)"

    async def test_unknown_prop_returns_literal(self, variable_context):
        handler = RandomHandler()
        result = await handler.resolve("unknown", "data", variable_context)
        assert result == "$(random)"

    def test_describe(self):
        handler = RandomHandler()
        descriptors = handler.describe()
        assert len(descriptors) == 2


class TestQueryHandler:
    async def test_resolve(self, variable_context):
        handler = QueryHandler()
        result = await handler.resolve(None, None, variable_context)
        assert result == "arg1 arg2 arg3"

    async def test_resolve_empty_args(self, variable_context):
        variable_context.raw_args = ""
        handler = QueryHandler()
        result = await handler.resolve(None, None, variable_context)
        assert result == ""


class TestIndexHandler:
    async def test_resolve_first_arg(self, variable_context):
        handler = IndexHandler()
        result = await handler.resolve_index(1, variable_context)
        assert result == "arg1"

    async def test_resolve_second_arg(self, variable_context):
        handler = IndexHandler()
        result = await handler.resolve_index(2, variable_context)
        assert result == "arg2"

    async def test_resolve_third_arg(self, variable_context):
        handler = IndexHandler()
        result = await handler.resolve_index(3, variable_context)
        assert result == "arg3"

    async def test_resolve_out_of_range(self, variable_context):
        handler = IndexHandler()
        result = await handler.resolve_index(10, variable_context)
        assert result == ""

    async def test_resolve_zero_returns_empty(self, variable_context):
        handler = IndexHandler()
        result = await handler.resolve_index(0, variable_context)
        assert result == ""

    async def test_resolve_no_args(self, variable_context):
        variable_context.raw_args = ""
        handler = IndexHandler()
        result = await handler.resolve_index(1, variable_context)
        assert result == ""

    def test_describe(self):
        handler = IndexHandler()
        descriptors = handler.describe()
        assert len(descriptors) == 3


# --- Registry tests ---


class TestVariableRegistry:
    async def test_process_simple_user(self, registry, variable_context):
        result = await registry.process("Hello $(user)!", variable_context)
        assert result == "Hello TestUser!"

    async def test_process_multiple_variables(self, registry, variable_context):
        result = await registry.process(
            "$(user) is in $(channel)", variable_context
        )
        assert result == "TestUser is in testchannel"

    async def test_process_no_variables(self, registry, variable_context):
        result = await registry.process("Just plain text.", variable_context)
        assert result == "Just plain text."

    async def test_process_unknown_variable_passthrough(
        self, registry, variable_context
    ):
        result = await registry.process("$(unknown) stays", variable_context)
        assert result == "$(unknown) stays"

    async def test_process_uses(self, registry, variable_context):
        result = await registry.process(
            "Used $(uses) times", variable_context
        )
        assert result == "Used 42 times"

    async def test_process_target(self, registry, variable_context):
        result = await registry.process(
            "Looking at $(target)", variable_context
        )
        assert result == "Looking at TargetUser"

    async def test_process_query(self, registry, variable_context):
        result = await registry.process("Args: $(query)", variable_context)
        assert result == "Args: arg1 arg2 arg3"

    async def test_process_index_variables(self, registry, variable_context):
        result = await registry.process(
            "$(1) and $(2)", variable_context
        )
        assert result == "arg1 and arg2"

    async def test_process_mixed_variables(self, registry, variable_context):
        result = await registry.process(
            "$(user) said $(1) in $(channel)", variable_context
        )
        assert result == "TestUser said arg1 in testchannel"

    @pytest.mark.django_db(transaction=True)
    async def test_process_count_get(
        self, registry, make_counter, variable_context
    ):
        make_counter(name="death", value=15)
        result = await registry.process(
            "Deaths: $(count.get death)", variable_context
        )
        assert result == "Deaths: 15"

    async def test_process_random_range(self, registry, variable_context):
        result = await registry.process(
            "Roll: $(random.range 1-6)", variable_context
        )
        value = int(result.replace("Roll: ", ""))
        assert 1 <= value <= 6

    async def test_process_random_pick(self, registry, variable_context):
        result = await registry.process(
            "$(random.pick yes,no)", variable_context
        )
        assert result in ("yes", "no")


class TestCreateRegistry:
    def test_creates_all_handlers(self):
        registry = create_registry()
        assert "user" in registry._handlers
        assert "target" in registry._handlers
        assert "channel" in registry._handlers
        assert "uses" in registry._handlers
        assert "count" in registry._handlers
        assert "random" in registry._handlers
        assert "query" in registry._handlers
        assert registry._index_handler is not None


class TestRegistrySchema:
    def test_schema_returns_all_descriptors(self):
        registry = create_registry()
        schema = registry.schema()
        assert isinstance(schema, list)
        assert len(schema) > 0

        namespaces = {entry["namespace"] for entry in schema}
        assert "user" in namespaces
        assert "target" in namespaces
        assert "channel" in namespaces
        assert "uses" in namespaces
        assert "count" in namespaces
        assert "random" in namespaces
        assert "query" in namespaces
        # Index handler contributes "1", "2", "N"
        assert "1" in namespaces

    def test_schema_entries_have_required_keys(self):
        registry = create_registry()
        schema = registry.schema()
        for entry in schema:
            assert "namespace" in entry
            assert "description" in entry
            assert "example" in entry
