"""Database helpers for the long-lived bot process.

Canonical form: synthhome's ``apps/core/db.py``. Copied rather than shared
across repos (no shared package exists), so keep this identical to that file
if either changes.
"""

from __future__ import annotations

from asgiref.sync import sync_to_async
from django.db import close_old_connections


async def release_connection() -> None:
    """Hand this thread's DB connection back to the pool.

    Django keeps one connection per thread and only releases it on ``close()``,
    which it normally does at the end of a request. ``runbot`` has no request
    cycle — one ``asyncio.run()`` for the process lifetime — so nothing ever
    calls it: the same connection is held from boot until the container dies.

    That is fine until the connection dies underneath us, which is exactly
    what happened on 2026-08-21: a shared-Postgres restart left every bot
    holding a dead connection, and nothing in the router or the three
    background tick loops (``accrual``, ``lizardbullets``, ``timedmessages``)
    ever gave it back, so the pool's own health check (``CONN_HEALTH_CHECKS``)
    never got a chance to run — it validates a connection when one is
    *acquired*, and this is what makes an acquisition happen. Neither half
    works alone: ``check`` without this still hands back the same dead
    connection, and this without ``check`` returns an unvalidated one.

    Call this at the top of ``event_message`` and at the top of every
    background tick loop's per-iteration body — before any ORM access, not
    only where a query happens to already sit. asgiref's default
    ``thread_sensitive`` executor pins every ``sync_to_async`` call in this
    process to one shared worker thread, so the connection this releases is
    the same one every one of those call sites would otherwise reuse; the
    repetition is not redundant; it is what keeps the outage window short no
    matter which loop happens to fire first after a recreate.

    Must be awaited rather than called directly — connections are
    thread-local, and the default ``thread_sensitive`` executor is the same
    thread the ORM calls run in.
    """
    await sync_to_async(close_old_connections)()
