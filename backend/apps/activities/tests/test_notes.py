"""
Note API tests: create on a client, scoped listing, author-only edits for
staff, manager override, and target immutability.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.activities.models import Note
from apps.clients.models import Client

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db

LIST_URL = reverse("activities:note-list")


def note_url(note_id):
    return reverse("activities:note-detail", args=[note_id])


@pytest.fixture
def manager():
    return User.objects.create_user(
        email="manager@example.com", password=PASSWORD, role=User.Role.MANAGER
    )


@pytest.fixture
def staff():
    return User.objects.create_user(
        email="staff@example.com", password=PASSWORD, role=User.Role.STAFF
    )


@pytest.fixture
def manager_api(manager):
    c = APIClient()
    c.force_authenticate(user=manager)
    return c


@pytest.fixture
def staff_api(staff):
    c = APIClient()
    c.force_authenticate(user=staff)
    return c


@pytest.fixture
def acme():
    return Client.objects.create(name="Acme Fintech")


def create_note(api, client_id, body="Called them; renewal likely in Q3."):
    return api.post(LIST_URL, {"body": body, "content_type": "client", "object_id": client_id})


def test_any_role_creates_note_on_client(staff_api, staff, acme):
    res = create_note(staff_api, acme.id)
    assert res.status_code == 201
    assert res.data["author"]["id"] == staff.id
    assert res.data["target"] == {"content_type": "client", "object_id": acme.id}
    assert Note.objects.get(pk=res.data["id"]).content_object == acme


def test_note_on_missing_client_rejected(manager_api):
    assert create_note(manager_api, 99999).status_code == 400


def test_list_requires_target_params(manager_api):
    assert manager_api.get(LIST_URL).status_code == 400


def test_list_scoped_to_object(manager_api, acme):
    other = Client.objects.create(name="Other Co")
    create_note(manager_api, acme.id, body="on acme")
    create_note(manager_api, other.id, body="on other")
    res = manager_api.get(LIST_URL, {"content_type": "client", "object_id": acme.id})
    assert res.data["count"] == 1
    assert res.data["results"][0]["body"] == "on acme"


def test_author_edits_own_note(staff_api, acme):
    note_id = create_note(staff_api, acme.id).data["id"]
    res = staff_api.patch(note_url(note_id), {"body": "updated"})
    assert res.status_code == 200
    assert res.data["body"] == "updated"


def test_staff_cannot_touch_someone_elses_note(manager_api, staff_api, acme):
    note_id = create_note(manager_api, acme.id).data["id"]
    assert staff_api.patch(note_url(note_id), {"body": "x"}).status_code == 403
    assert staff_api.delete(note_url(note_id)).status_code == 403


def test_manager_deletes_any_note(manager_api, staff_api, acme):
    note_id = create_note(staff_api, acme.id).data["id"]
    assert manager_api.delete(note_url(note_id)).status_code == 204


def test_patch_cannot_move_note_to_another_object(manager_api, acme):
    other = Client.objects.create(name="Other Co")
    note_id = create_note(manager_api, acme.id).data["id"]
    res = manager_api.patch(note_url(note_id), {"body": "same", "object_id": other.id})
    assert res.status_code == 200
    assert Note.objects.get(pk=note_id).object_id == acme.id  # target untouched
