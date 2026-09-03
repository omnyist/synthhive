from __future__ import annotations

import json

import pytest
from django.contrib.auth.models import User
from django.test import Client

from core.models import Alias
from core.models import Bot
from core.models import Channel
from core.models import Command
from core.models import Counter
from core.models import Invite
from core.models import TwitchProfile

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture()
def test_bot():
    return Bot.objects.create(
        name="TestBot",
        twitch_user_id="66977097",
        twitch_username="testbot",
    )


@pytest.fixture()
def test_channel(test_bot):
    return Channel.objects.create(
        bot=test_bot,
        twitch_channel_id="99999",
        twitch_channel_name="testchannel",
        is_active=True,
    )


@pytest.fixture()
def user_with_profile(test_channel):
    """Create a Django user with a TwitchProfile matching the test channel."""
    user = User.objects.create_user(username="avalonstar", password="testpass")
    TwitchProfile.objects.create(
        user=user,
        twitch_id="99999",
        twitch_username="avalonstar",
        twitch_display_name="Avalonstar",
        twitch_avatar="https://example.com/avatar.png",
    )
    return user


@pytest.fixture()
def other_user():
    """Create a user who does NOT own the test channel."""
    user = User.objects.create_user(username="otheruser", password="testpass")
    TwitchProfile.objects.create(
        user=user,
        twitch_id="11111",
        twitch_username="otheruser",
        twitch_display_name="OtherUser",
    )
    return user


@pytest.fixture()
def authed_client(user_with_profile):
    """A test client logged in as the channel owner."""
    c = Client(enforce_csrf_checks=False)
    c.login(username="avalonstar", password="testpass")
    return c


@pytest.fixture()
def unauthed_client():
    """A test client with no session."""
    return Client()


@pytest.fixture()
def other_client(other_user):
    """A test client logged in as a user who doesn't own the channel."""
    c = Client(enforce_csrf_checks=False)
    c.login(username="otheruser", password="testpass")
    return c


def _make_cmd(test_channel, name="test", response="Hello!", **kwargs):
    """Helper to create a command in the test channel."""
    defaults = {
        "channel": test_channel,
        "name": name,
        "response": response,
        "enabled": True,
    }
    defaults.update(kwargs)
    return Command.objects.create(**defaults)


class TestMeEndpoint:
    def test_returns_user_info(self, authed_client, test_channel):
        response = authed_client.get("/api/v1/me")
        assert response.status_code == 200
        data = response.json()
        assert data["twitch_id"] == "99999"
        assert data["twitch_display_name"] == "Avalonstar"
        assert data["is_staff"] is False
        assert len(data["channels"]) == 1
        assert data["channels"][0]["name"] == "testchannel"

    def test_staff_flag_true_for_staff(self, staff_client):
        data = staff_client.get("/api/v1/me").json()
        assert data["is_staff"] is True

    def test_unauthenticated_returns_401(self, unauthed_client):
        response = unauthed_client.get("/api/v1/me")
        assert response.status_code == 401


class TestChannelsEndpoint:
    def test_lists_owned_channels(self, authed_client, test_channel):
        response = authed_client.get("/api/v1/channels/")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 1
        assert data["items"][0]["name"] == "testchannel"

    def test_excludes_other_channels(self, other_client, test_channel):
        response = other_client.get("/api/v1/channels/")
        assert response.status_code == 200
        assert response.json()["items"] == []

    def test_unauthenticated_returns_401(self, unauthed_client):
        response = unauthed_client.get("/api/v1/channels/")
        assert response.status_code == 401


class TestCommandList:
    def test_lists_all_commands(self, authed_client, test_channel):
        _make_cmd(test_channel, name="lurk", response="/me lurks")
        _make_cmd(test_channel, name="conch", enabled=False)

        response = authed_client.get(
            f"/api/v1/commands/channels/{test_channel.twitch_channel_name}/"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        names = [c["name"] for c in data["items"]]
        assert "lurk" in names
        assert "conch" in names

    def test_not_found_for_non_owner(self, other_client, test_channel):
        response = other_client.get(
            f"/api/v1/commands/channels/{test_channel.twitch_channel_name}/"
        )
        assert response.status_code == 404

    def test_unauthenticated_returns_401(self, unauthed_client, test_channel):
        response = unauthed_client.get(
            f"/api/v1/commands/channels/{test_channel.twitch_channel_name}/"
        )
        assert response.status_code == 401


class TestCommandCreate:
    def test_creates_command(self, authed_client, test_channel):
        response = authed_client.post(
            f"/api/v1/commands/channels/{test_channel.twitch_channel_name}/",
            data=json.dumps({"name": "hello", "response": "Hello $(user)!"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "hello"
        assert data["response"] == "Hello $(user)!"
        assert data["created_by"] == "Avalonstar"
        assert Command.objects.filter(
            channel=test_channel, name="hello"
        ).exists()

    def test_create_with_config(self, authed_client, test_channel):
        response = authed_client.post(
            f"/api/v1/commands/channels/{test_channel.twitch_channel_name}/",
            data=json.dumps({
                "name": "flask",
                "type": "lottery",
                "config": {
                    "odds": 25,
                    "success": "You win!",
                    "failure": "Nope.",
                },
            }),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "lottery"
        assert data["config"]["odds"] == 25

    def test_not_found_for_non_owner(self, other_client, test_channel):
        response = other_client.post(
            f"/api/v1/commands/channels/{test_channel.twitch_channel_name}/",
            data=json.dumps({"name": "nope"}),
            content_type="application/json",
        )
        assert response.status_code == 404


class TestCommandGet:
    def test_get_single_command(self, authed_client, test_channel):
        cmd = _make_cmd(test_channel, name="lurk", response="/me lurks")
        response = authed_client.get(f"/api/v1/commands/{cmd.id}/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "lurk"

    def test_forbidden_for_non_owner(self, other_client, test_channel):
        cmd = _make_cmd(test_channel, name="lurk")
        response = other_client.get(f"/api/v1/commands/{cmd.id}/")
        assert response.status_code == 403


class TestCommandUpdate:
    def test_updates_response(self, authed_client, test_channel):
        cmd = _make_cmd(test_channel, name="lurk", response="old response")
        response = authed_client.patch(
            f"/api/v1/commands/{cmd.id}/",
            data=json.dumps({"response": "new response"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        cmd.refresh_from_db()
        assert cmd.response == "new response"

    def test_updates_multiple_fields(self, authed_client, test_channel):
        cmd = _make_cmd(test_channel, name="lurk")
        response = authed_client.patch(
            f"/api/v1/commands/{cmd.id}/",
            data=json.dumps({
                "enabled": False,
                "mod_only": True,
                "cooldown_seconds": 30,
            }),
            content_type="application/json",
        )
        assert response.status_code == 200
        cmd.refresh_from_db()
        assert cmd.enabled is False
        assert cmd.mod_only is True
        assert cmd.cooldown_seconds == 30

    def test_forbidden_for_non_owner(self, other_client, test_channel):
        cmd = _make_cmd(test_channel, name="lurk")
        response = other_client.patch(
            f"/api/v1/commands/{cmd.id}/",
            data=json.dumps({"response": "hacked"}),
            content_type="application/json",
        )
        assert response.status_code == 403
        cmd.refresh_from_db()
        assert cmd.response != "hacked"


class TestCommandDelete:
    def test_deletes_command(self, authed_client, test_channel):
        cmd = _make_cmd(test_channel, name="bye")
        response = authed_client.delete(f"/api/v1/commands/{cmd.id}/")
        assert response.status_code == 200
        assert not Command.objects.filter(pk=cmd.id).exists()

    def test_forbidden_for_non_owner(self, other_client, test_channel):
        cmd = _make_cmd(test_channel, name="safe")
        response = other_client.delete(f"/api/v1/commands/{cmd.id}/")
        assert response.status_code == 403
        assert Command.objects.filter(pk=cmd.id).exists()


class TestVariableSchema:
    def test_returns_schema(self, authed_client):
        response = authed_client.get("/api/v1/variables/schema/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0
        namespaces = [v["namespace"] for v in data]
        assert "user" in namespaces

    def test_unauthenticated_returns_401(self, unauthed_client):
        response = unauthed_client.get("/api/v1/variables/schema/")
        assert response.status_code == 401


def _make_counter(test_channel, name="death", **kwargs):
    """Helper to create a counter in the test channel."""
    defaults = {
        "channel": test_channel,
        "name": name,
        "label": "",
        "value": 0,
    }
    defaults.update(kwargs)
    return Counter.objects.create(**defaults)


def _make_alias(test_channel, name="ct", target="count death", **kwargs):
    """Helper to create an alias in the test channel."""
    defaults = {
        "channel": test_channel,
        "name": name,
        "target": target,
    }
    defaults.update(kwargs)
    return Alias.objects.create(**defaults)


class TestCounterList:
    def test_lists_all_counters(self, authed_client, test_channel):
        _make_counter(test_channel, name="death", label="Death Count", value=14)
        _make_counter(test_channel, name="scare", value=3)

        response = authed_client.get(
            f"/api/v1/counters/channels/{test_channel.twitch_channel_name}/"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        names = [c["name"] for c in data["items"]]
        assert "death" in names
        assert "scare" in names

    def test_not_found_for_non_owner(self, other_client, test_channel):
        response = other_client.get(
            f"/api/v1/counters/channels/{test_channel.twitch_channel_name}/"
        )
        assert response.status_code == 404

    def test_unauthenticated_returns_401(self, unauthed_client, test_channel):
        response = unauthed_client.get(
            f"/api/v1/counters/channels/{test_channel.twitch_channel_name}/"
        )
        assert response.status_code == 401


class TestCounterCreate:
    def test_creates_counter(self, authed_client, test_channel):
        response = authed_client.post(
            f"/api/v1/counters/channels/{test_channel.twitch_channel_name}/",
            data=json.dumps({"name": "death", "label": "Death Count"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "death"
        assert data["label"] == "Death Count"
        assert data["value"] == 0
        assert Counter.objects.filter(
            channel=test_channel, name="death"
        ).exists()

    def test_duplicate_returns_409(self, authed_client, test_channel):
        _make_counter(test_channel, name="death")
        response = authed_client.post(
            f"/api/v1/counters/channels/{test_channel.twitch_channel_name}/",
            data=json.dumps({"name": "death"}),
            content_type="application/json",
        )
        assert response.status_code == 409

    def test_not_found_for_non_owner(self, other_client, test_channel):
        response = other_client.post(
            f"/api/v1/counters/channels/{test_channel.twitch_channel_name}/",
            data=json.dumps({"name": "death"}),
            content_type="application/json",
        )
        assert response.status_code == 404


class TestCounterUpdate:
    def test_updates_fields(self, authed_client, test_channel):
        counter = _make_counter(test_channel, name="death", value=10)
        response = authed_client.patch(
            f"/api/v1/counters/{counter.id}/",
            data=json.dumps({"label": "Death Count", "value": 42}),
            content_type="application/json",
        )
        assert response.status_code == 200
        counter.refresh_from_db()
        assert counter.label == "Death Count"
        assert counter.value == 42

    def test_forbidden_for_non_owner(self, other_client, test_channel):
        counter = _make_counter(test_channel, name="death")
        response = other_client.patch(
            f"/api/v1/counters/{counter.id}/",
            data=json.dumps({"value": 99}),
            content_type="application/json",
        )
        assert response.status_code == 403


class TestCounterDelete:
    def test_deletes_counter(self, authed_client, test_channel):
        counter = _make_counter(test_channel, name="death")
        response = authed_client.delete(f"/api/v1/counters/{counter.id}/")
        assert response.status_code == 200
        assert not Counter.objects.filter(pk=counter.id).exists()

    def test_forbidden_for_non_owner(self, other_client, test_channel):
        counter = _make_counter(test_channel, name="death")
        response = other_client.delete(f"/api/v1/counters/{counter.id}/")
        assert response.status_code == 403
        assert Counter.objects.filter(pk=counter.id).exists()


class TestAliasList:
    def test_lists_all_aliases(self, authed_client, test_channel):
        _make_alias(test_channel, name="ct", target="count death")
        _make_alias(test_channel, name="fc", target="followage")

        response = authed_client.get(
            f"/api/v1/aliases/channels/{test_channel.twitch_channel_name}/"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        names = [a["name"] for a in data["items"]]
        assert "ct" in names
        assert "fc" in names

    def test_not_found_for_non_owner(self, other_client, test_channel):
        response = other_client.get(
            f"/api/v1/aliases/channels/{test_channel.twitch_channel_name}/"
        )
        assert response.status_code == 404

    def test_unauthenticated_returns_401(self, unauthed_client, test_channel):
        response = unauthed_client.get(
            f"/api/v1/aliases/channels/{test_channel.twitch_channel_name}/"
        )
        assert response.status_code == 401


class TestAliasCreate:
    def test_creates_alias(self, authed_client, test_channel):
        response = authed_client.post(
            f"/api/v1/aliases/channels/{test_channel.twitch_channel_name}/",
            data=json.dumps({"name": "ct", "target": "count death"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "ct"
        assert data["target"] == "count death"
        assert Alias.objects.filter(
            channel=test_channel, name="ct"
        ).exists()

    def test_duplicate_returns_409(self, authed_client, test_channel):
        _make_alias(test_channel, name="ct")
        response = authed_client.post(
            f"/api/v1/aliases/channels/{test_channel.twitch_channel_name}/",
            data=json.dumps({"name": "ct", "target": "count death"}),
            content_type="application/json",
        )
        assert response.status_code == 409

    def test_not_found_for_non_owner(self, other_client, test_channel):
        response = other_client.post(
            f"/api/v1/aliases/channels/{test_channel.twitch_channel_name}/",
            data=json.dumps({"name": "ct", "target": "count death"}),
            content_type="application/json",
        )
        assert response.status_code == 404


class TestAliasUpdate:
    def test_updates_fields(self, authed_client, test_channel):
        alias = _make_alias(test_channel, name="ct", target="count death")
        response = authed_client.patch(
            f"/api/v1/aliases/{alias.id}/",
            data=json.dumps({"target": "count scare"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        alias.refresh_from_db()
        assert alias.target == "count scare"

    def test_forbidden_for_non_owner(self, other_client, test_channel):
        alias = _make_alias(test_channel, name="ct")
        response = other_client.patch(
            f"/api/v1/aliases/{alias.id}/",
            data=json.dumps({"target": "count scare"}),
            content_type="application/json",
        )
        assert response.status_code == 403


class TestAliasDelete:
    def test_deletes_alias(self, authed_client, test_channel):
        alias = _make_alias(test_channel, name="ct")
        response = authed_client.delete(f"/api/v1/aliases/{alias.id}/")
        assert response.status_code == 200
        assert not Alias.objects.filter(pk=alias.id).exists()

    def test_forbidden_for_non_owner(self, other_client, test_channel):
        alias = _make_alias(test_channel, name="ct")
        response = other_client.delete(f"/api/v1/aliases/{alias.id}/")
        assert response.status_code == 403
        assert Alias.objects.filter(pk=alias.id).exists()


@pytest.fixture()
def staff_client(db):
    """A test client logged in as a staff user with a TwitchProfile."""
    user = User.objects.create_user(
        username="staffer", password="testpass", is_staff=True
    )
    TwitchProfile.objects.create(
        user=user,
        twitch_id="55555",
        twitch_username="staffer",
        twitch_display_name="Staffer",
        is_approved=True,
    )
    c = Client(enforce_csrf_checks=False)
    c.login(username="staffer", password="testpass")
    return c


class TestInviteCreate:
    def test_staff_can_create_invite(self, staff_client):
        response = staff_client.post("/api/v1/invites/")
        assert response.status_code == 200
        data = response.json()
        assert data["code"]
        assert data["status"] == "pending"
        assert Invite.objects.filter(code=data["code"]).exists()

    def test_non_staff_forbidden(self, authed_client):
        response = authed_client.post("/api/v1/invites/")
        assert response.status_code == 403
        assert not Invite.objects.exists()

    def test_unauthenticated_returns_401(self, unauthed_client):
        response = unauthed_client.post("/api/v1/invites/")
        assert response.status_code == 401


class TestInviteList:
    def test_lists_own_invites(self, staff_client):
        staff_client.post("/api/v1/invites/")
        staff_client.post("/api/v1/invites/")
        response = staff_client.get("/api/v1/invites/")
        assert response.status_code == 200
        assert len(response.json()) == 2


class TestInviteDelete:
    def test_deletes_own_invite(self, staff_client):
        created = staff_client.post("/api/v1/invites/").json()
        invite = Invite.objects.get(code=created["code"])
        response = staff_client.delete(f"/api/v1/invites/{invite.id}/")
        assert response.status_code == 200
        assert not Invite.objects.filter(pk=invite.id).exists()

    def test_cannot_delete_others_invite(self, staff_client, authed_client):
        created = staff_client.post("/api/v1/invites/").json()
        invite = Invite.objects.get(code=created["code"])
        response = authed_client.delete(f"/api/v1/invites/{invite.id}/")
        assert response.status_code == 404
        assert Invite.objects.filter(pk=invite.id).exists()


def _make_skill_row(test_channel, name="lizardroulette", **kwargs):
    from core.models import Skill

    defaults = {"channel": test_channel, "name": name, "enabled": True, "config": {}}
    defaults.update(kwargs)
    return Skill.objects.create(**defaults)


class TestSkillList:
    def test_lists_skills(self, authed_client, test_channel):
        _make_skill_row(test_channel, name="lizardroulette", config={"odds": 20})
        _make_skill_row(test_channel, name="dungeon", enabled=False)

        response = authed_client.get(
            f"/api/v1/skills/channels/{test_channel.twitch_channel_name}/"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 2
        by_name = {s["name"]: s for s in data["items"]}
        assert by_name["lizardroulette"]["config"] == {"odds": 20}
        assert by_name["dungeon"]["enabled"] is False

    def test_not_found_for_non_owner(self, other_client, test_channel):
        response = other_client.get(
            f"/api/v1/skills/channels/{test_channel.twitch_channel_name}/"
        )
        assert response.status_code == 404


class TestSkillCreate:
    def test_creates_skill_with_valid_config(self, authed_client, test_channel):
        from core.models import Skill

        response = authed_client.post(
            f"/api/v1/skills/channels/{test_channel.twitch_channel_name}/",
            data=json.dumps({"name": "lizardroulette", "config": {"odds": 33}}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert Skill.objects.filter(
            channel=test_channel, name="lizardroulette"
        ).exists()

    def test_invalid_config_returns_422(self, authed_client, test_channel):
        response = authed_client.post(
            f"/api/v1/skills/channels/{test_channel.twitch_channel_name}/",
            data=json.dumps({"name": "lizardroulette", "config": {"odds": 500}}),
            content_type="application/json",
        )
        assert response.status_code == 422
        assert "odds" in response.json()["detail"]

    def test_typo_key_returns_422(self, authed_client, test_channel):
        response = authed_client.post(
            f"/api/v1/skills/channels/{test_channel.twitch_channel_name}/",
            data=json.dumps(
                {"name": "lizardroulette", "config": {"cooldown_repsonse": "x"}}
            ),
            content_type="application/json",
        )
        assert response.status_code == 422

    def test_unknown_skill_returns_422(self, authed_client, test_channel):
        response = authed_client.post(
            f"/api/v1/skills/channels/{test_channel.twitch_channel_name}/",
            data=json.dumps({"name": "nonexistent"}),
            content_type="application/json",
        )
        assert response.status_code == 422

    def test_duplicate_returns_409(self, authed_client, test_channel):
        _make_skill_row(test_channel, name="lizardroulette")
        response = authed_client.post(
            f"/api/v1/skills/channels/{test_channel.twitch_channel_name}/",
            data=json.dumps({"name": "lizardroulette"}),
            content_type="application/json",
        )
        assert response.status_code == 409


class TestSkillUpdate:
    def test_toggles_enabled(self, authed_client, test_channel):
        skill = _make_skill_row(test_channel, name="lizardroulette")
        response = authed_client.patch(
            f"/api/v1/skills/{skill.id}/",
            data=json.dumps({"enabled": False}),
            content_type="application/json",
        )
        assert response.status_code == 200
        skill.refresh_from_db()
        assert skill.enabled is False

    def test_updates_config_with_validation(self, authed_client, test_channel):
        skill = _make_skill_row(test_channel, name="lizardroulette")
        response = authed_client.patch(
            f"/api/v1/skills/{skill.id}/",
            data=json.dumps({"config": {"odds": 42, "birthday_mode": True}}),
            content_type="application/json",
        )
        assert response.status_code == 200
        skill.refresh_from_db()
        assert skill.config == {"odds": 42, "birthday_mode": True}

    def test_invalid_config_rejected_and_unsaved(self, authed_client, test_channel):
        skill = _make_skill_row(test_channel, name="lizardroulette", config={"odds": 20})
        response = authed_client.patch(
            f"/api/v1/skills/{skill.id}/",
            data=json.dumps({"config": {"odds": -5}}),
            content_type="application/json",
        )
        assert response.status_code == 422
        skill.refresh_from_db()
        assert skill.config == {"odds": 20}

    def test_forbidden_for_non_owner(self, other_client, test_channel):
        skill = _make_skill_row(test_channel, name="lizardroulette")
        response = other_client.patch(
            f"/api/v1/skills/{skill.id}/",
            data=json.dumps({"enabled": False}),
            content_type="application/json",
        )
        assert response.status_code == 403


class TestSkillDelete:
    def test_deletes_skill(self, authed_client, test_channel):
        from core.models import Skill

        skill = _make_skill_row(test_channel, name="lizardroulette")
        response = authed_client.delete(f"/api/v1/skills/{skill.id}/")
        assert response.status_code == 200
        assert not Skill.objects.filter(pk=skill.id).exists()


class TestSkillSchemaEndpoint:
    def test_returns_schemas(self, authed_client):
        response = authed_client.get("/api/v1/skills/schema/")
        assert response.status_code == 200
        data = response.json()
        assert data["lizardroulette"]["properties"]["odds"]["default"] == 16
        assert data["markov"] is None

    def test_unauthenticated_returns_401(self, unauthed_client):
        response = unauthed_client.get("/api/v1/skills/schema/")
        assert response.status_code == 401


class TestCommandConfigValidationAPI:
    def test_create_lottery_with_bad_config_422(self, authed_client, test_channel):
        response = authed_client.post(
            f"/api/v1/commands/channels/{test_channel.twitch_channel_name}/",
            data=json.dumps({
                "name": "flask",
                "type": "lottery",
                "config": {"odds": 500},
            }),
            content_type="application/json",
        )
        assert response.status_code == 422

    def test_create_with_typo_key_422(self, authed_client, test_channel):
        response = authed_client.post(
            f"/api/v1/commands/channels/{test_channel.twitch_channel_name}/",
            data=json.dumps({
                "name": "conch",
                "type": "random_list",
                "config": {"resposnes": ["typo"]},
            }),
            content_type="application/json",
        )
        assert response.status_code == 422

    def test_update_config_validated_against_type(self, authed_client, test_channel):
        cmd = _make_cmd(test_channel, name="flask", type="lottery",
                        config={"odds": 10})
        response = authed_client.patch(
            f"/api/v1/commands/{cmd.id}/",
            data=json.dumps({"config": {"odds": 0}}),
            content_type="application/json",
        )
        assert response.status_code == 422
        cmd.refresh_from_db()
        assert cmd.config == {"odds": 10}


class TestCampaignCrudProxies:
    """The campaign CRUD proxies relay Synthfunc responses — including
    error details like 409 slug conflicts — to the dashboard."""

    @staticmethod
    def _stub(monkeypatch, name, result):
        """Patch a core.synthfunc coroutine, capturing call args."""
        calls = []

        async def fake(*args, **kwargs):
            calls.append((args, kwargs))
            return result

        import core.synthfunc

        monkeypatch.setattr(core.synthfunc, name, fake)
        return calls

    def test_list_campaigns(self, authed_client, test_channel, monkeypatch):
        self._stub(
            monkeypatch,
            "list_campaigns",
            [{"id": "abc", "name": "25th Anniversary"}],
        )
        response = authed_client.get("/api/v1/campaigns/channels/testchannel/")
        assert response.status_code == 200
        assert response.json()[0]["name"] == "25th Anniversary"

    def test_list_synthfunc_down_502(self, authed_client, test_channel, monkeypatch):
        self._stub(monkeypatch, "list_campaigns", None)
        response = authed_client.get("/api/v1/campaigns/channels/testchannel/")
        assert response.status_code == 502

    def test_create_relays_409_detail(self, authed_client, test_channel, monkeypatch):
        self._stub(
            monkeypatch,
            "create_campaign",
            (409, {"detail": "A campaign with slug 'x' already exists."}),
        )
        response = authed_client.post(
            "/api/v1/campaigns/channels/testchannel/",
            data=json.dumps({
                "name": "X",
                "start_date": "2026-08-01T00:00:00Z",
                "end_date": "2026-08-31T23:59:59Z",
            }),
            content_type="application/json",
        )
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    def test_create_passes_through(self, authed_client, test_channel, monkeypatch):
        calls = self._stub(
            monkeypatch,
            "create_campaign",
            (200, {"id": "new-id", "name": "Awesome August"}),
        )
        response = authed_client.post(
            "/api/v1/campaigns/channels/testchannel/",
            data=json.dumps({
                "name": "Awesome August",
                "start_date": "2026-08-01T00:00:00Z",
                "end_date": "2026-08-31T23:59:59Z",
                "is_active": True,
            }),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["id"] == "new-id"
        sent = calls[0][0][1]
        assert sent["is_active"] is True

    def test_detail_404_when_missing(self, authed_client, test_channel, monkeypatch):
        self._stub(monkeypatch, "get_campaign", None)
        response = authed_client.get("/api/v1/campaigns/channels/testchannel/some-id/")
        assert response.status_code == 404

    def test_update_excludes_unset_fields(self, authed_client, test_channel, monkeypatch):
        calls = self._stub(
            monkeypatch, "update_campaign", (200, {"id": "abc", "name": "Renamed"})
        )
        response = authed_client.patch(
            "/api/v1/campaigns/channels/testchannel/abc/",
            data=json.dumps({"name": "Renamed"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert calls[0][0][2] == {"name": "Renamed"}

    def test_milestone_add_and_delete(self, authed_client, test_channel, monkeypatch):
        add_calls = self._stub(
            monkeypatch,
            "create_milestone",
            (200, {"id": "abc", "milestones": [{"id": "m1"}]}),
        )
        response = authed_client.post(
            "/api/v1/campaigns/channels/testchannel/abc/milestones/",
            data=json.dumps({"threshold": 500, "title": "Demon's Souls"}),
            content_type="application/json",
        )
        assert response.status_code == 200
        assert add_calls[0][0][2]["goal_unit"] == "subs"

        self._stub(
            monkeypatch, "delete_milestone", (200, {"id": "abc", "milestones": []})
        )
        response = authed_client.delete(
            "/api/v1/campaigns/channels/testchannel/milestones/m1/"
        )
        assert response.status_code == 200
        assert response.json()["milestones"] == []

    def test_non_owner_404(self, other_client, test_channel, monkeypatch):
        self._stub(monkeypatch, "list_campaigns", [])
        response = other_client.get("/api/v1/campaigns/channels/testchannel/")
        assert response.status_code == 404

    def test_unauthed_401(self, unauthed_client, test_channel):
        response = unauthed_client.get("/api/v1/campaigns/channels/testchannel/")
        assert response.status_code == 401


class TestOverlayEndpoints:
    """Overlay endpoints are gated by the channel's overlay key —
    capability-URL auth for OBS browser sources, no session."""

    @staticmethod
    def _stub(monkeypatch, name, result):
        async def fake(*args, **kwargs):
            return result

        import core.synthfunc

        monkeypatch.setattr(core.synthfunc, name, fake)

    def test_valid_key_serves_campaign(self, unauthed_client, test_channel, monkeypatch):
        self._stub(monkeypatch, "get_active_campaign", {"name": "Awesome August 2026"})
        response = unauthed_client.get(
            f"/api/v1/overlay/channels/testchannel/campaign/?key={test_channel.overlay_key}"
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Awesome August 2026"

    def test_wrong_key_403(self, unauthed_client, test_channel):
        response = unauthed_client.get(
            "/api/v1/overlay/channels/testchannel/campaign/?key=00000000-0000-0000-0000-000000000000"
        )
        assert response.status_code == 403

    def test_missing_key_403(self, unauthed_client, test_channel):
        response = unauthed_client.get("/api/v1/overlay/channels/testchannel/campaign/")
        assert response.status_code == 403

    def test_bidwars_with_key(self, unauthed_client, test_channel, monkeypatch):
        self._stub(monkeypatch, "get_bid_wars", [{"title": "Fire vs Ice"}])
        response = unauthed_client.get(
            f"/api/v1/overlay/channels/testchannel/bidwars/?key={test_channel.overlay_key}"
        )
        assert response.status_code == 200
        assert response.json()[0]["title"] == "Fire vs Ice"

    def test_urls_requires_session(self, unauthed_client, test_channel):
        response = unauthed_client.get("/api/v1/overlay/channels/testchannel/urls/")
        assert response.status_code == 401

    def test_urls_returns_key_and_widgets(self, authed_client, test_channel):
        response = authed_client.get("/api/v1/overlay/channels/testchannel/urls/")
        assert response.status_code == 200
        data = response.json()
        assert data["overlay_key"] == str(test_channel.overlay_key)
        assert any("goals" in w["path"] for w in data["widgets"])
        assert all(data["overlay_key"] in w["path"] for w in data["widgets"])

    def test_channels_get_distinct_keys(self, test_bot, test_channel):
        other = Channel.objects.create(
            bot=test_bot,
            twitch_channel_id="88888",
            twitch_channel_name="otherchannel",
            is_active=True,
        )
        assert other.overlay_key != test_channel.overlay_key


class TestPublicEventPage:
    """The public campaign endpoint needs no auth — it feeds the
    shareable event page that replaced Spoonee's pastebin."""

    @staticmethod
    def _stub(monkeypatch, name, result):
        async def fake(*args, **kwargs):
            return result

        import core.synthfunc

        monkeypatch.setattr(core.synthfunc, name, fake)

    def test_anonymous_fetch_by_slug(self, unauthed_client, test_channel, monkeypatch):
        self._stub(
            monkeypatch,
            "list_campaigns",
            [{"id": "c1", "slug": "awesome-august-2026", "name": "Awesome August 2026"}],
        )
        self._stub(
            monkeypatch,
            "get_campaign",
            {"id": "c1", "name": "Awesome August 2026", "milestones": []},
        )
        self._stub(monkeypatch, "get_bid_wars", [{"title": "War"}])
        response = unauthed_client.get(
            "/api/v1/public/channels/testchannel/campaigns/awesome-august-2026/"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Awesome August 2026"
        assert data["bid_wars"][0]["title"] == "War"

    def test_unknown_slug_404(self, unauthed_client, test_channel, monkeypatch):
        self._stub(monkeypatch, "list_campaigns", [{"id": "c1", "slug": "other"}])
        response = unauthed_client.get(
            "/api/v1/public/channels/testchannel/campaigns/awesome-august-2026/"
        )
        assert response.status_code == 404

    def test_unknown_channel_404(self, unauthed_client, test_channel):
        response = unauthed_client.get(
            "/api/v1/public/channels/nobody/campaigns/whatever/"
        )
        assert response.status_code == 404


class TestPublicDomainResolution:
    """A tenant's own domain (spoonee.tv) maps to their channel so the
    frontend can render the same public routes it already has."""

    def test_resolves_a_configured_domain(self, unauthed_client, test_channel):
        test_channel.custom_domain = "spoonee.tv"
        test_channel.save(update_fields=["custom_domain"])

        response = unauthed_client.get("/api/v1/public/domains/spoonee.tv/")

        assert response.status_code == 200
        assert response.json() == {"channel_slug": "testchannel"}

    def test_unconfigured_domain_404s(self, unauthed_client, test_channel):
        response = unauthed_client.get("/api/v1/public/domains/nobody.tv/")

        assert response.status_code == 404

    def test_lookup_is_case_insensitive_and_ignores_port(
        self, unauthed_client, test_channel
    ):
        """A browser's location.hostname is always bare and lowercase,
        but nothing should depend on the caller normalising it first."""
        test_channel.custom_domain = "spoonee.tv"
        test_channel.save(update_fields=["custom_domain"])

        response = unauthed_client.get("/api/v1/public/domains/SPOONEE.TV:8443/")

        assert response.status_code == 200
        assert response.json() == {"channel_slug": "testchannel"}

    def test_inactive_channel_is_not_resolvable(self, unauthed_client, test_channel):
        test_channel.custom_domain = "spoonee.tv"
        test_channel.is_active = False
        test_channel.save(update_fields=["custom_domain", "is_active"])

        response = unauthed_client.get("/api/v1/public/domains/spoonee.tv/")

        assert response.status_code == 404


class TestOverlayCampaignFallback:
    """With no active campaign, the overlay serves the nearest
    current-window or upcoming event so widgets render at zero instead
    of disappearing. Past events never surface."""

    @staticmethod
    def _stub(monkeypatch, name, result):
        async def fake(*args, **kwargs):
            return result

        import core.synthfunc

        monkeypatch.setattr(core.synthfunc, name, fake)

    def _get(self, test_channel):
        return Client().get(
            f"/api/v1/overlay/channels/testchannel/campaign/?key={test_channel.overlay_key}"
        )

    def test_active_campaign_wins(self, test_channel, monkeypatch):
        self._stub(monkeypatch, "get_active_campaign", {"name": "Live"})
        response = self._get(test_channel)
        assert response.json()["name"] == "Live"

    def test_falls_back_to_window_campaign(self, test_channel, monkeypatch):
        self._stub(monkeypatch, "get_active_campaign", None)
        self._stub(monkeypatch, "list_campaigns", [
            {"id": "past", "start_date": "2020-01-01", "end_date": "2020-02-01"},
            {"id": "now", "start_date": "2020-01-01", "end_date": "2099-01-01"},
        ])
        self._stub(monkeypatch, "get_campaign", {"id": "now", "name": "Window"})
        response = self._get(test_channel)
        assert response.json()["name"] == "Window"

    def test_falls_back_to_soonest_upcoming(self, test_channel, monkeypatch):
        self._stub(monkeypatch, "get_active_campaign", None)
        self._stub(monkeypatch, "list_campaigns", [
            {"id": "later", "start_date": "2098-06-01", "end_date": "2098-07-01"},
            {"id": "sooner", "start_date": "2097-06-01", "end_date": "2097-07-01"},
        ])

        picked = {}

        async def fake_get_campaign(slug, campaign_id):
            picked["id"] = campaign_id
            return {"id": campaign_id, "name": "Upcoming"}

        import core.synthfunc

        monkeypatch.setattr(core.synthfunc, "get_campaign", fake_get_campaign)
        response = self._get(test_channel)
        assert response.json()["name"] == "Upcoming"
        assert picked["id"] == "sooner"

    def test_past_only_returns_null(self, test_channel, monkeypatch):
        self._stub(monkeypatch, "get_active_campaign", None)
        self._stub(monkeypatch, "list_campaigns", [
            {"id": "past", "start_date": "2020-01-01", "end_date": "2020-02-01"},
        ])
        response = self._get(test_channel)
        assert response.status_code == 200
        assert response.json() is None


class TestPendingGiftsRoute:
    """Regression: /pending-gifts/ must be registered before the
    /{bid_war_id}/ routes — Django resolves by path first, so the
    literal segment used to match {bid_war_id} on a PATCH-only route
    and every GET came back 405."""

    @staticmethod
    def _stub(monkeypatch, result):
        async def fake(*args, **kwargs):
            return result

        import core.synthfunc

        monkeypatch.setattr(core.synthfunc, "get_pending_gifts", fake)

    def test_get_returns_200_not_405(self, authed_client, test_channel, monkeypatch):
        self._stub(monkeypatch, [{"event_id": "e1", "gifter": "G", "count": 5}])
        response = authed_client.get(
            "/api/v1/bidwars/channels/testchannel/pending-gifts/"
        )
        assert response.status_code == 200
        assert response.json()[0]["count"] == 5

    def test_patch_by_war_id_still_routes(self, authed_client, test_channel, monkeypatch):
        async def fake(*args, **kwargs):
            return {"id": "w1", "status": "closed"}

        import core.synthfunc

        monkeypatch.setattr(core.synthfunc, "set_bid_war_status", fake)
        response = authed_client.patch(
            "/api/v1/bidwars/channels/testchannel/some-war-id/",
            data=json.dumps({"status": "closed"}),
            content_type="application/json",
        )
        assert response.status_code == 200


class TestActivityProxy:
    def test_activity_feed(self, authed_client, test_channel, monkeypatch):
        async def fake(*args, **kwargs):
            return [{"id": "e1", "event_type": "channel.subscribe", "who": "N"}]

        import core.synthfunc

        monkeypatch.setattr(core.synthfunc, "get_recent_activity", fake)
        response = authed_client.get("/api/v1/events/channels/testchannel/activity/")
        assert response.status_code == 200
        assert response.json()[0]["who"] == "N"

    def test_unauthed_401(self, unauthed_client, test_channel):
        response = unauthed_client.get("/api/v1/events/channels/testchannel/activity/")
        assert response.status_code == 401
