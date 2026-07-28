"""
Client API tests: happy paths, every role's permission boundary (matrix §8:
admin/manager full, staff read-only), GST validation, soft delete,
search/filter/ordering.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db

LIST_URL = reverse("clients:client-list")


def detail_url(client_id):
    return reverse("clients:client-detail", args=[client_id])


@pytest.fixture
def manager():
    return User.objects.create_user(
        email="manager@example.com", password=PASSWORD, first_name="Max", role=User.Role.MANAGER
    )


@pytest.fixture
def staff():
    return User.objects.create_user(
        email="staff@example.com", password=PASSWORD, first_name="Stan", role=User.Role.STAFF
    )


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def manager_api(api, manager):
    api.force_authenticate(user=manager)
    return api


@pytest.fixture
def staff_api(staff):
    c = APIClient()
    c.force_authenticate(user=staff)
    return c


def payload(**overrides):
    data = {
        "name": "Acme Fintech Pvt Ltd",
        "industry": "Fintech",
        "website": "https://acme.example",
        "email": "info@acme.example",
        "phone": "+91-9800000000",
        "gst_number": "29ABCDE1234F1Z5",
        "address_line1": "42 MG Road",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postal_code": "560001",
        "status": "active",
    }
    data.update(overrides)
    return data


@pytest.fixture
def acme(manager, manager_api):
    return Client.objects.get(pk=manager_api.post(LIST_URL, payload()).data["id"])


# ------------------------------------------------------------- permissions


def test_anonymous_gets_401(api):
    assert api.get(LIST_URL).status_code == 401


def test_staff_can_read(staff_api, acme):
    assert staff_api.get(LIST_URL).status_code == 200
    assert staff_api.get(detail_url(acme.id)).status_code == 200


def test_staff_cannot_write(staff_api, acme):
    assert staff_api.post(LIST_URL, payload(name="X", gst_number="")).status_code == 403
    assert staff_api.patch(detail_url(acme.id), {"city": "Pune"}).status_code == 403
    assert staff_api.delete(detail_url(acme.id)).status_code == 403


# -------------------------------------------------------------------- CRUD


def test_manager_creates_client(manager_api, manager):
    res = manager_api.post(LIST_URL, payload(account_manager_id=manager.id))
    assert res.status_code == 201
    # Response is the full detail shape, with the manager embedded as an object.
    assert res.data["account_manager"] == {
        "id": manager.id,
        "name": "Max",
        "email": manager.email,
    }
    assert res.data["contacts"] == []
    assert res.data["gst_number"] == "29ABCDE1234F1Z5"


def test_gst_is_normalized_to_uppercase(manager_api):
    res = manager_api.post(LIST_URL, payload(gst_number="29abcde1234f1z5 "))
    assert res.status_code == 201
    assert res.data["gst_number"] == "29ABCDE1234F1Z5"


def test_invalid_gst_rejected(manager_api):
    res = manager_api.post(LIST_URL, payload(gst_number="INVALID-GST"))
    assert res.status_code == 400
    assert "gst_number" in res.data


def test_duplicate_gst_rejected(manager_api, acme):
    res = manager_api.post(LIST_URL, payload(name="Other Co"))
    assert res.status_code == 400
    assert "gst_number" in res.data


def test_two_clients_may_both_omit_gst(manager_api):
    assert manager_api.post(LIST_URL, payload(name="A Co", gst_number="")).status_code == 201
    assert manager_api.post(LIST_URL, payload(name="B Co", gst_number="")).status_code == 201


def test_invalid_phone_rejected(manager_api):
    res = manager_api.post(LIST_URL, payload(phone="not-a-phone"))
    assert res.status_code == 400
    assert "phone" in res.data


def test_phone_accepts_prefixed_and_local_formats(manager_api):
    valid = ["+91 98765 43210", "+1 (415) 555-0132", "0484-2334455"]
    for i, phone in enumerate(valid):
        res = manager_api.post(LIST_URL, payload(name=f"Phone Co {i}", gst_number="", phone=phone))
        assert res.status_code == 201, (phone, res.data)


def test_duplicate_name_rejected(manager_api, acme):
    res = manager_api.post(LIST_URL, payload(gst_number=""))
    assert res.status_code == 400
    assert "name" in res.data


def test_patch_updates_and_returns_detail(manager_api, acme):
    res = manager_api.patch(detail_url(acme.id), {"status": "inactive", "city": "Pune"})
    assert res.status_code == 200
    assert res.data["status"] == "inactive"
    assert res.data["city"] == "Pune"
    assert res.data["name"] == acme.name  # untouched fields survive PATCH


def test_put_is_rejected(manager_api, acme):
    assert manager_api.put(detail_url(acme.id), payload()).status_code == 405


def test_delete_is_soft(manager_api, acme):
    assert manager_api.delete(detail_url(acme.id)).status_code == 204
    # Invisible to the API…
    assert manager_api.get(detail_url(acme.id)).status_code == 404
    assert manager_api.get(LIST_URL).data["count"] == 0
    # …but the row survives for audit.
    acme.refresh_from_db()
    assert acme.is_active is False


# ------------------------------------------------- search / filter / order


def test_filter_by_status(manager_api):
    manager_api.post(LIST_URL, payload(name="Active Co", gst_number=""))
    manager_api.post(LIST_URL, payload(name="Lead Co", gst_number="", status="prospect"))
    res = manager_api.get(LIST_URL, {"status": "prospect"})
    assert [row["name"] for row in res.data["results"]] == ["Lead Co"]


def test_search_by_name(manager_api, acme):
    # Distinct email/website too — search also scans those fields.
    manager_api.post(
        LIST_URL,
        payload(
            name="Zeta Retail",
            gst_number="",
            email="hello@zeta.example",
            website="https://zeta.example",
        ),
    )
    res = manager_api.get(LIST_URL, {"search": "acme"})
    assert res.data["count"] == 1
    assert res.data["results"][0]["name"] == acme.name


def test_ordering_whitelist(manager_api):
    manager_api.post(LIST_URL, payload(name="Bravo", gst_number=""))
    manager_api.post(LIST_URL, payload(name="Alpha", gst_number=""))
    res = manager_api.get(LIST_URL, {"ordering": "name"})
    assert [r["name"] for r in res.data["results"]] == ["Alpha", "Bravo"]


def test_list_rows_carry_contact_count(manager_api, acme):
    acme.contacts.create(name="Priya")
    res = manager_api.get(LIST_URL)
    assert res.data["results"][0]["contact_count"] == 1


# ------------------------------------------------- instant duplicate check

CHECK_URL = reverse("clients:client-check")


def test_check_reports_taken_name_case_insensitively(manager_api, acme):
    res = manager_api.get(CHECK_URL, {"name": acme.name.upper()})
    assert res.status_code == 200
    assert res.data == {"name_taken": True}


def test_check_reports_free_name_and_gstin(manager_api, acme):
    res = manager_api.get(CHECK_URL, {"name": "Zeta Retail", "gst_number": "27ZZZZZ9999Z9Z9"})
    assert res.data == {"name_taken": False, "gst_number_taken": False}


def test_check_normalizes_gstin_before_matching(manager_api, acme):
    res = manager_api.get(CHECK_URL, {"gst_number": " 29abcde1234f1z5 "})
    assert res.data == {"gst_number_taken": True}


def test_check_excludes_the_record_being_edited(manager_api, acme):
    res = manager_api.get(
        CHECK_URL, {"name": acme.name, "gst_number": acme.gst_number, "exclude": acme.id}
    )
    assert res.data == {"name_taken": False, "gst_number_taken": False}


def test_check_still_sees_soft_deleted_rows(manager_api, acme):
    # The unique constraints include soft-deleted rows, so the pre-check must
    # too — otherwise it says "available" for a value the INSERT would reject.
    manager_api.delete(detail_url(acme.id))
    res = manager_api.get(CHECK_URL, {"name": acme.name})
    assert res.data == {"name_taken": True}


def test_check_is_readable_by_staff(staff_api, acme):
    # GET, so ReadOnlyForStaff allows it — staff never create, but the form
    # code shouldn't need role branching just to validate.
    assert staff_api.get(CHECK_URL, {"name": acme.name}).status_code == 200
