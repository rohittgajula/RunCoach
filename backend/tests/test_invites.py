"""docs/DEPLOY.md §2.2: invite-only registration."""

import datetime as dt

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from apps.athletes.invites import consume_invite
from apps.athletes.models import InviteCode

REGISTER = "/api/auth/register/"
MODE = "/api/auth/registration/"


@pytest.fixture(autouse=True)
def _no_throttling(settings):
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_RATES": {k: None for k in settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]},
    }


@pytest.fixture
def invite_mode(settings):
    settings.REGISTRATION_MODE = "invite"


def register(client, username="newbie", **extra):
    body = {"username": username, "password": "correct-horse-battery-9", **extra}
    return client.post(REGISTER, body, content_type="application/json")


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["open", "invite", "closed"])
def test_mode_endpoint_is_public(client, settings, mode):
    settings.REGISTRATION_MODE = mode
    response = client.get(MODE)
    assert response.status_code == 200
    assert response.json() == {"mode": mode}


@pytest.mark.django_db
def test_open_mode_needs_no_code(client, settings):
    settings.REGISTRATION_MODE = "open"
    assert register(client).status_code == 201


@pytest.mark.django_db
def test_closed_mode_refuses_everyone(client, settings):
    settings.REGISTRATION_MODE = "closed"
    code = InviteCode.objects.create()
    response = register(client, invite_code=code.code)
    assert response.status_code == 403
    assert "detail" in response.json()
    assert not User.objects.filter(username="newbie").exists()
    code.refresh_from_db()
    assert code.uses == 0


@pytest.mark.django_db
def test_invite_mode_requires_a_code(client, invite_mode):
    response = register(client)
    assert response.status_code == 400
    assert "invite_code" in response.json()
    assert not User.objects.exists()


@pytest.mark.django_db
def test_valid_code_registers_once_only(client, invite_mode):
    code = InviteCode.objects.create(note="for Asha")
    assert register(client, invite_code=code.code.lower()).status_code == 201
    code.refresh_from_db()
    assert code.uses == 1

    second = register(client, username="second", invite_code=code.code)
    assert second.status_code == 400
    assert "invite_code" in second.json()
    assert not User.objects.filter(username="second").exists()


@pytest.mark.django_db
def test_multi_use_code_counts_down(client, invite_mode):
    code = InviteCode.objects.create(max_uses=2)
    assert register(client, "a1", invite_code=code.code).status_code == 201
    assert register(client, "a2", invite_code=code.code).status_code == 201
    assert register(client, "a3", invite_code=code.code).status_code == 400


@pytest.mark.django_db
def test_expired_and_unknown_codes_are_refused(client, invite_mode):
    expired = InviteCode.objects.create(expires_at=timezone.now() - dt.timedelta(minutes=1))
    assert register(client, invite_code=expired.code).status_code == 400
    assert register(client, invite_code="NOPE12345678").status_code == 400
    future = InviteCode.objects.create(expires_at=timezone.now() + dt.timedelta(days=1))
    assert register(client, invite_code=future.code).status_code == 201


@pytest.mark.django_db
def test_failed_registration_gives_the_slot_back(client, invite_mode):
    """Consumed inside the registration transaction: a weak password (or any later
    failure) must not burn the invite."""
    code = InviteCode.objects.create()
    assert register(client, invite_code=code.code, password="abc").status_code == 400
    code.refresh_from_db()
    assert code.uses == 0
    assert register(client, invite_code=code.code).status_code == 201


@pytest.mark.django_db
def test_consume_is_a_single_conditional_update(invite_mode):
    """The last slot goes to exactly one caller: the check and the increment are one
    UPDATE ... WHERE uses < max_uses, never read-then-write."""
    code = InviteCode.objects.create(max_uses=1)
    assert consume_invite(code.code) is True
    assert consume_invite(code.code) is False
    code.refresh_from_db()
    assert code.uses == 1


@pytest.mark.django_db
def test_stale_instance_cannot_overspend(invite_mode):
    """A caller holding a stale copy that still says uses=0 cannot win the slot."""
    code = InviteCode.objects.create(max_uses=1)
    stale = InviteCode.objects.get(pk=code.pk)
    assert consume_invite(code.code)
    assert stale.is_usable  # its view is stale...
    assert not consume_invite(stale.code)  # ...but the database decides


@pytest.mark.django_db
def test_codes_are_generated_and_normalised():
    a, b = InviteCode.objects.create(), InviteCode.objects.create(code=" abc-123 ")
    assert len(a.code) == 12 and a.code.isupper()
    assert b.code == "ABC-123"


@pytest.mark.django_db
def test_admin_generate_button_and_action(client):
    admin = User.objects.create_superuser("boss", password="correct-horse-battery-7")
    client.force_login(admin)
    response = client.post("/admin/athletes/invitecode/generate/")
    assert response.status_code == 302
    assert InviteCode.objects.count() == 1

    first = InviteCode.objects.get()
    response = client.post("/admin/athletes/invitecode/", {
        "action": "generate_like_selected", "_selected_action": [first.pk],
    })
    assert response.status_code == 302
    assert InviteCode.objects.count() == 2
    assert client.get("/admin/athletes/invitecode/").status_code == 200
