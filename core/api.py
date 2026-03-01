from __future__ import annotations

import uuid

from ninja import Router
from ninja import Schema

router = Router(tags=["commands"])


class CommandSchema(Schema):
    id: uuid.UUID
    name: str
    response: str
    enabled: bool
    use_count: int
    cooldown_seconds: int
    mod_only: bool


class CommandCreateSchema(Schema):
    name: str
    response: str
    cooldown_seconds: int = 0
    mod_only: bool = False


@router.get("/channels/{channel_id}/", response=list[CommandSchema])
async def list_commands(request, channel_id: uuid.UUID):
    """List all commands for a channel."""
    from core.models import Command

    commands = []
    async for cmd in Command.objects.filter(
        channel_id=channel_id, enabled=True
    ).order_by("name"):
        commands.append(cmd)
    return commands
