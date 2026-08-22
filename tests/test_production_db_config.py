"""The production database config, tested despite never running under pytest.

The pool is deliberately disabled under pytest (its worker thread wedges
teardown), which means the config that actually ships lives in a branch no
ordinary test executes. That blind spot let a green suite ship a crash-loop on
2026-08-22. These tests look at the branch directly.

Tier 1 asserts on the pure function's output — milliseconds, no database.
Tier 2 builds the pool through Django's own code path and takes one cursor
through it, exercising the exact line that raised in production.
"""

from __future__ import annotations

import inspect
import re
import socket
from copy import deepcopy

import pytest
from django.conf import settings

from synthhive.settings import production_database_extras

PROD = production_database_extras("django.db.backends.postgresql", under_test=False)


def test_the_shipped_branch_is_visible_at_all():
    assert PROD, (
        "production_database_extras returned nothing for the production case — "
        "the prod branch has moved out of the function and is untestable again"
    )


def test_health_checks_are_on():
    # Django forwards this to psycopg_pool as the pool's `check` callback.
    # Left False the pool validates nothing, and a Postgres restart leaves it
    # serving dead connections forever (2026-08-21).
    assert PROD.get("CONN_HEALTH_CHECKS") is True


def _django_pool_reserved_kwargs() -> set[str]:
    """The kwargs Django's postgresql backend passes to ConnectionPool itself.

    Read from the installed Django rather than hardcoded, so this tracks the
    version uv.lock actually ships instead of rotting when Django changes.
    """
    from django.db.backends.postgresql.base import DatabaseWrapper

    src = inspect.getsource(DatabaseWrapper.pool.fget)
    call = re.search(r"ConnectionPool\((.*?)\*\*pool_options", src, re.S)
    assert call, "could not find ConnectionPool(...) in Django's pool property"
    return set(re.findall(r"(\w+)=", call.group(1)))


def test_pool_options_do_not_collide_with_djangos_own_kwargs():
    """Supplying e.g. `check` yourself raises "got multiple values for keyword
    argument 'check'" on the first cursor — the 2026-08-22 crash-loop."""
    pool = PROD["OPTIONS"]["pool"]
    assert pool is True or isinstance(pool, dict), "pool must be True or a dict"
    if isinstance(pool, dict):
        collisions = set(pool) & _django_pool_reserved_kwargs()
        assert not collisions, (
            f"pool options collide with kwargs Django passes itself: {collisions}"
        )


def _db_reachable() -> bool:
    d = settings.DATABASES["default"]
    try:
        with socket.create_connection(
            (d.get("HOST") or "localhost", int(d.get("PORT") or 5432)), timeout=2
        ):
            return True
    except OSError:
        return False


@pytest.mark.skipif(
    not _db_reachable(),
    reason="no Postgres reachable — tier-2 pool check needs one (CI always has it)",
)
def test_the_production_pool_actually_opens_a_cursor(django_db_blocker):
    """Build the pool with the production OPTIONS through Django's own code
    path. This catches a collision from either side of the Django/psycopg_pool
    boundary, whichever of them changes next.

    django_db_blocker (not the django_db mark) because this deliberately does
    NOT want the test database machinery — it builds its own handler with the
    production config; the blocker just patches ensure_connection globally.
    """
    alias = deepcopy(settings.DATABASES["default"])
    alias.pop("CONN_MAX_AGE", None)  # pooling rejects persistent connections
    alias.update(production_database_extras(alias["ENGINE"], under_test=False))
    from django.db.utils import ConnectionHandler

    handler = ConnectionHandler({"default": alias})
    conn = handler["default"]
    try:
        with django_db_blocker.unblock():
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                assert cur.fetchone()[0] == 1
        assert conn.pool is not None, "production config did not build a pool"
    finally:
        # Shut the pool's worker threads down explicitly — leaving them alive
        # is the teardown wedge that keeps the pool off under pytest.
        conn.close()
        conn.close_pool()
