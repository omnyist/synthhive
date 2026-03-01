from __future__ import annotations

import importlib

import pytest

# Migration module has a numeric prefix so we need importlib
_migration = importlib.import_module("core.migrations.0003_migrate_variable_syntax")
migrate_variables_forward = _migration.migrate_variables_forward
migrate_variables_backward = _migration.migrate_variables_backward


class _FakeCommand:
    """Minimal stand-in for a Command model instance."""

    def __init__(self, response):
        self.response = response
        self._saved = False

    def save(self, update_fields=None):
        self._saved = True


class _FakeQuerySet:
    """Minimal stand-in for Command.objects.all()."""

    def __init__(self, commands):
        self._commands = commands

    def all(self):
        return self._commands


class _FakeApps:
    """Minimal stand-in for apps.get_model()."""

    def __init__(self, commands):
        self._commands = commands

    def get_model(self, app, model):
        return type("Command", (), {"objects": _FakeQuerySet(self._commands)})


class TestMigrateVariablesForward:
    """Test the forward data migration: old syntax → new syntax."""

    def test_count_to_uses(self):
        cmd = _FakeCommand("Used $(count) times")
        apps = _FakeApps([cmd])
        migrate_variables_forward(apps, None)
        assert cmd.response == "Used $(uses) times"
        assert cmd._saved

    def test_count_get_not_touched(self):
        cmd = _FakeCommand("Deaths: $(count.get death)")
        apps = _FakeApps([cmd])
        migrate_variables_forward(apps, None)
        # $(count.get ...) should NOT be replaced
        assert cmd.response == "Deaths: $(count.get death)"
        assert not cmd._saved

    def test_random_range(self):
        cmd = _FakeCommand("Roll: $(random 1-100)")
        apps = _FakeApps([cmd])
        migrate_variables_forward(apps, None)
        assert cmd.response == "Roll: $(random.range 1-100)"
        assert cmd._saved

    def test_pick_to_random_pick(self):
        cmd = _FakeCommand("$(pick heads,tails)")
        apps = _FakeApps([cmd])
        migrate_variables_forward(apps, None)
        assert cmd.response == "$(random.pick heads,tails)"
        assert cmd._saved

    def test_multiple_replacements_in_one_command(self):
        cmd = _FakeCommand(
            "$(user) rolled $(random 1-6) and has $(count) uses. $(pick yes,no)"
        )
        apps = _FakeApps([cmd])
        migrate_variables_forward(apps, None)
        assert cmd.response == (
            "$(user) rolled $(random.range 1-6) and has $(uses) uses. "
            "$(random.pick yes,no)"
        )
        assert cmd._saved

    def test_no_changes_no_save(self):
        cmd = _FakeCommand("Hello $(user)!")
        apps = _FakeApps([cmd])
        migrate_variables_forward(apps, None)
        assert cmd.response == "Hello $(user)!"
        assert not cmd._saved

    def test_user_and_target_untouched(self):
        cmd = _FakeCommand("$(user) targets $(target)")
        apps = _FakeApps([cmd])
        migrate_variables_forward(apps, None)
        assert cmd.response == "$(user) targets $(target)"
        assert not cmd._saved


class TestMigrateVariablesBackward:
    """Test the reverse data migration: new syntax → old syntax."""

    def test_uses_to_count(self):
        cmd = _FakeCommand("Used $(uses) times")
        apps = _FakeApps([cmd])
        migrate_variables_backward(apps, None)
        assert cmd.response == "Used $(count) times"
        assert cmd._saved

    def test_random_range_to_random(self):
        cmd = _FakeCommand("Roll: $(random.range 1-100)")
        apps = _FakeApps([cmd])
        migrate_variables_backward(apps, None)
        assert cmd.response == "Roll: $(random 1-100)"
        assert cmd._saved

    def test_random_pick_to_pick(self):
        cmd = _FakeCommand("$(random.pick heads,tails)")
        apps = _FakeApps([cmd])
        migrate_variables_backward(apps, None)
        assert cmd.response == "$(pick heads,tails)"
        assert cmd._saved

    def test_roundtrip(self):
        """Forward then backward should return to original."""
        original = "$(user) rolled $(random 1-6) with $(count) uses. $(pick a,b)"
        cmd = _FakeCommand(original)
        apps = _FakeApps([cmd])

        migrate_variables_forward(apps, None)
        assert cmd.response != original

        migrate_variables_backward(apps, None)
        assert cmd.response == original

    def test_no_changes_no_save(self):
        cmd = _FakeCommand("Hello $(user)!")
        apps = _FakeApps([cmd])
        migrate_variables_backward(apps, None)
        assert not cmd._saved
