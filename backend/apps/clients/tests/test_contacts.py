"""
Contact API tests: nested create/list under a client, flat update/delete,
the single-primary invariant, and staff read-only enforcement.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client, Contact

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db


def contacts_url(client_id):
    return reverse("clients:client-contacts", args=[client_id])


def contact_url(contact_id):
    return reverse("clients:contact-detail", args=[contact_id])


@pytest.fixture
def manager():
    return User.objects.create_user(
        email="manager@example.com", password=PASSWORD, role=User.Role.MANAGER
    )


@pytest.fixture
def manager_api(manager):
    c = APIClient()
    c.force_authenticate(user=manager)
    return c


@pytest.fixture
def staff_api():
    staff = User.objects.create_user(
        email="staff@example.com", password=PASSWORD, role=User.Role.STAFF
    )
    c = APIClient()
    c.force_authenticate(user=staff)
    return c


@pytest.fixture
def acme():
    return Client.objects.create(name="Acme Fintech")


def test_nested_create_takes_client_from_url(manager_api, acme):
    res = manager_api.post(
        contacts_url(acme.id),
        {
            "name": "Priya Sharma",
            "email": "priya@acme.example",
            "position": "CTO",
            "is_primary": True,
        },
    )
    assert res.status_code == 201
    contact = Contact.objects.get(pk=res.data["id"])
    assert contact.client == acme  # from the URL, not the body
    assert res.data["is_primary"] is True


def test_contact_invalid_phone_rejected(manager_api, acme):
    res = manager_api.post(contacts_url(acme.id), {"name": "Priya", "phone": "call me maybe"})
    assert res.status_code == 400
    assert "phone" in res.data


def test_nested_list_is_paginated(manager_api, acme):
    acme.contacts.create(name="A")
    acme.contacts.create(name="B")
    res = manager_api.get(contacts_url(acme.id))
    assert res.status_code == 200
    assert res.data["count"] == 2


def test_new_primary_demotes_old_primary(manager_api, acme):
    first = acme.contacts.create(name="Old Primary", is_primary=True)
    res = manager_api.post(contacts_url(acme.id), {"name": "New Primary", "is_primary": True})
    assert res.status_code == 201
    first.refresh_from_db()
    assert first.is_primary is False
    assert acme.contacts.filter(is_primary=True).count() == 1


def test_patch_promoting_contact_demotes_sibling(manager_api, acme):
    primary = acme.contacts.create(name="P", is_primary=True)
    other = acme.contacts.create(name="O")
    res = manager_api.patch(contact_url(other.id), {"is_primary": True})
    assert res.status_code == 200
    primary.refresh_from_db()
    assert primary.is_primary is False


def test_flat_update_and_delete(manager_api, acme):
    contact = acme.contacts.create(name="Priya")
    res = manager_api.patch(contact_url(contact.id), {"position": "CEO"})
    assert res.status_code == 200
    assert res.data["position"] == "CEO"
    assert manager_api.delete(contact_url(contact.id)).status_code == 204
    assert not Contact.objects.filter(pk=contact.pk).exists()  # hard delete (§4)


def test_staff_read_only(staff_api, acme):
    contact = acme.contacts.create(name="Priya")
    assert staff_api.get(contacts_url(acme.id)).status_code == 200
    assert staff_api.post(contacts_url(acme.id), {"name": "X"}).status_code == 403
    assert staff_api.patch(contact_url(contact.id), {"name": "X"}).status_code == 403
    assert staff_api.delete(contact_url(contact.id)).status_code == 403


def test_contacts_of_soft_deleted_client_are_invisible(manager_api, acme):
    contact = acme.contacts.create(name="Priya")
    acme.is_active = False
    acme.save()
    assert manager_api.get(contacts_url(acme.id)).status_code == 404
    assert manager_api.get(contact_url(contact.id)).status_code == 404
