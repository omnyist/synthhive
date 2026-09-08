"""The production database config, tested despite never running under pytest.

The pool is deliberately disabled under pytest (its worker thread wedges
teardown), which means the config that actually ships lives in a branch no
ordinary test executes. That blind spot let a green suite ship a crash-loop on
2026-08-22. These tests look at the branch directly.

Tier 1 (the pure function's output, the reserved-kwargs collision check) now
lives in synthlib's own test suite — it covers every caller. This file keeps
only what synthlib's suite cannot know: that THIS module's own call site
passes THIS module's own numbers (2/20/10, the 2026-07-31 pool-exhaustion
fix — not the 1/4 the other six modules use), and the Tier 2 integration
test that builds a real pool through Django's own code path.
"""

from __future__ import annotations

import socket
from copy import deepcopy

import pytest
from django.conf import settings
from synthlib.django.db import production_database_extras

# Rebuilt explicitly with this module's own kwargs -- settings.DATABASES
# never carries the production branch during a test run (the pool is
# disabled under pytest), so this is the only way to see what
# synthhive/settings.py's own call site actually produces.
PROD = production_database_extras(
    "django.db.backends.postgresql",
    under_test=False,
    pool_min_size=2,
    pool_max_size=20,
    pool_timeout=10,
)


def test_this_modules_pool_kwargs_are_the_ones_that_actually_ship():
    """synthlib's own tests prove the function; this proves synthhive's call
    site passes synthhive's own numbers (2/20/10), not another module's
    1/4 or a silently-picked default."""
    assert PROD["OPTIONS"]["pool"] == {"min_size": 2, "max_size": 20, "timeout": 10}


def _pooled_postgres_available() -> bool:
    """Can this machine actually build the production pool?

    Two conditions, and the engine is the one that matters. A local checkout
    with no DATABASE_URL falls back to SQLite, for which
    production_database_extras() correctly returns {} — no pool, by design.
    An earlier version of this guard only probed a socket, so an empty
    HOST/PORT resolved to localhost:5432, found whatever else was listening
    there, and ran the test against a SQLite alias: it then failed on a pool
    that was never supposed to exist. A guard that reports "your environment
    is wrong" when the environment is fine is worse than no guard, because
    the failure it invents is indistinguishable from the regression it was
    written to catch.
    """
    d = settings.DATABASES["default"]
    if d["ENGINE"] != "django.db.backends.postgresql":
        return False
    try:
        with socket.create_connection(
            (d.get("HOST") or "localhost", int(d.get("PORT") or 5432)), timeout=2
        ):
            return True
    except OSError:
        return False


@pytest.mark.skipif(
    not _pooled_postgres_available(),
    reason="not a pooled-Postgres environment — tier-2 pool check needs one (CI always has it)",
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
    alias.update(
        production_database_extras(
            alias["ENGINE"],
            under_test=False,
            pool_min_size=2,
            pool_max_size=20,
            pool_timeout=10,
        )
    )
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
