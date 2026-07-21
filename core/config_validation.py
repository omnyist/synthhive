"""Config validation for skills and command types.

Skills declare pydantic schemas on their handlers
(`SkillHandler.config_schema`); command types declare theirs here.
Every config write path (API, admin) validates through this module so
a typo'd key or out-of-range value is rejected at save time instead of
surfacing as broken behavior — or, in the dungeon's case, a KeyError
after money has already been debited.

Validated configs are persisted sparsely (`exclude_unset`): rows only
store what the owner actually set, so defaults keep living in code and
can evolve without rewriting every row.
"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import ValidationError


def _format_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "config"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts[:5])


# --- Skills ---


def validate_skill_config(
    skill_name: str, config: dict | None
) -> tuple[dict, str | None]:
    """Validate a skill's config against its handler schema.

    Returns (normalized_config, error). Skills without a declared
    schema pass through untouched.
    """
    from bot.skills import SKILL_REGISTRY
    from bot.skills import discover_skills

    discover_skills()
    handler = SKILL_REGISTRY.get(skill_name)
    if handler is None or handler.config_schema is None:
        return config or {}, None

    try:
        model = handler.config_schema.model_validate(config or {})
    except ValidationError as exc:
        return config or {}, _format_error(exc)

    return model.model_dump(exclude_unset=True, mode="json"), None


def skill_schemas() -> dict[str, dict | None]:
    """JSON schema per registered skill (None for schema-less skills)."""
    from bot.skills import SKILL_REGISTRY
    from bot.skills import discover_skills

    discover_skills()
    return {
        name: (
            handler.config_schema.model_json_schema()
            if handler.config_schema
            else None
        )
        for name, handler in sorted(SKILL_REGISTRY.items())
    }


# --- Command types ---


class TextCommandConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cooldown_response: str | None = None


class LotteryCommandConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    odds: int = Field(default=5, ge=1, le=100)
    success: str = "$(user) wins!"
    failure: str = "Better luck next time!"
    cooldown_response: str | None = None


class RandomListCommandConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    responses: list[str] = Field(default_factory=list)
    prefix: str = ""
    cooldown_response: str | None = None


class CounterCommandConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counter_name: str | None = None
    cooldown_response: str | None = None


COMMAND_CONFIG_SCHEMAS: dict[str, type[BaseModel]] = {
    "text": TextCommandConfig,
    "lottery": LotteryCommandConfig,
    "random_list": RandomListCommandConfig,
    "counter": CounterCommandConfig,
}


def validate_command_config(
    command_type: str, config: dict | None
) -> tuple[dict, str | None]:
    """Validate a command's config against its type schema."""
    schema = COMMAND_CONFIG_SCHEMAS.get(command_type)
    if schema is None:
        return config or {}, None

    try:
        model = schema.model_validate(config or {})
    except ValidationError as exc:
        return config or {}, _format_error(exc)

    return model.model_dump(exclude_unset=True, mode="json"), None
