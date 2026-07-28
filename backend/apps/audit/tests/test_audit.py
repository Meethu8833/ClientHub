"""
Audit log tests: automatic model auditing (create/update/soft-delete/hard-
delete diffs), sensitive-field exclusion, auth events (login, failed login,
logout), request context capture (actor + IP via middleware), and the
admin-only read-only API.
"""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.clients.models import Client

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db

LIST_URL = reverse("audit:auditlog-list")


@pytest.fixture
def admin():
    return User.objects.create_user(
        email="admin@example.com", password=PASSWORD, first_name="Ada", role=User.Role.ADMIN
    )


@pytest.fixture
def staff():
    return User.objects.create_user(
        email="staff@example.com", password=PASSWORD, first_name="Stan", role=User.Role.STAFF
    )


@pytest.fixture
def admin_api(admin):
    c = APIClient()
    c.force_authenticate(user=admin)
    return c


def make_client(**overrides):
    data = {"name": "Acme Fintech Pvt Ltd", "email": "info@acme.example"}
    data.update(overrides)
    return Client.objects.create(**data)


# ------------------------------------------------------ model signal auditing


class TestModelAuditing:
    def test_create_is_logged(self):
        acme = make_client()
        entry = AuditLog.objects.get(action=AuditLog.Action.CREATED, object_id=acme.pk)
        assert entry.target_repr == str(acme)
        assert entry.actor is None  # ORM call outside a request → system

    def test_update_logs_field_diff(self):
        acme = make_client()
        acme.industry = "Fintech"
        acme.save()
        entry = AuditLog.objects.get(action=AuditLog.Action.UPDATED, object_id=acme.pk)
        assert entry.changes["industry"] == {"from": "", "to": "Fintech"}
        # Untouched fields must not appear in the diff.
        assert "name" not in entry.changes

    def test_noop_save_logs_nothing(self):
        acme = make_client()
        acme.save()  # nothing changed (updated_at churn is excluded)
        assert not AuditLog.objects.filter(
            action=AuditLog.Action.UPDATED, object_id=acme.pk
        ).exists()

    def test_soft_delete_and_restore_are_classified(self):
        acme = make_client()
        acme.is_active = False
        acme.save()
        assert AuditLog.objects.filter(
            action=AuditLog.Action.SOFT_DELETED, object_id=acme.pk
        ).exists()

        acme.is_active = True
        acme.save()
        assert AuditLog.objects.filter(
            action=AuditLog.Action.RESTORED, object_id=acme.pk
        ).exists()

    def test_hard_delete_keeps_final_snapshot(self):
        acme = make_client()
        pk = acme.pk
        acme.delete()
        entry = AuditLog.objects.get(action=AuditLog.Action.DELETED, object_id=pk)
        assert entry.changes["name"] == "Acme Fintech Pvt Ltd"

    def test_password_never_appears_in_changes(self, staff):
        staff.set_password("N3w!password456")
        staff.first_name = "Stanley"
        staff.save()
        entry = AuditLog.objects.filter(
            action=AuditLog.Action.UPDATED, object_id=staff.pk
        ).latest("created_at")
        assert "password" not in entry.changes
        assert entry.changes["first_name"] == {"from": "Stan", "to": "Stanley"}


# ------------------------------------------------------------- request context


class TestRequestContext:
    def test_api_write_records_actor_and_ip(self, admin, admin_api):
        response = admin_api.post(
            reverse("clients:client-list"),
            {"name": "Ctx Corp", "email": "ctx@example.com", "status": "active"},
            REMOTE_ADDR="10.1.2.3",
        )
        assert response.status_code == 201
        entry = AuditLog.objects.get(
            action=AuditLog.Action.CREATED, object_id=response.data["id"]
        )
        assert entry.actor == admin
        assert entry.ip_address == "10.1.2.3"
        assert entry.method == "POST"

    def test_x_forwarded_for_wins_over_remote_addr(self, admin, admin_api):
        response = admin_api.post(
            reverse("clients:client-list"),
            {"name": "Proxy Corp", "email": "proxy@example.com", "status": "active"},
            REMOTE_ADDR="172.18.0.2",  # what Nginx would show
            HTTP_X_FORWARDED_FOR="203.0.113.9, 172.18.0.2",
        )
        entry = AuditLog.objects.get(
            action=AuditLog.Action.CREATED, object_id=response.data["id"]
        )
        assert entry.ip_address == "203.0.113.9"


# ----------------------------------------------------------------- auth events


class TestAuthEvents:
    def test_successful_login_is_logged(self, admin):
        response = APIClient().post(
            reverse("accounts:login"), {"email": admin.email, "password": PASSWORD}
        )
        assert response.status_code == 200
        entry = AuditLog.objects.get(action=AuditLog.Action.LOGIN)
        assert entry.actor == admin

    def test_failed_login_is_logged_without_password(self, admin):
        response = APIClient().post(
            reverse("accounts:login"), {"email": admin.email, "password": "wrong"}
        )
        assert response.status_code == 401
        entry = AuditLog.objects.get(action=AuditLog.Action.LOGIN_FAILED)
        assert entry.changes == {"email": admin.email}
        assert entry.actor is None

    def test_logout_is_logged_with_actor_from_refresh_token(self, admin):
        api = APIClient()
        api.post(reverse("accounts:login"), {"email": admin.email, "password": PASSWORD})
        response = api.post(reverse("accounts:logout"))
        assert response.status_code == 200
        entry = AuditLog.objects.get(action=AuditLog.Action.LOGOUT)
        assert entry.actor == admin


# -------------------------------------------------------------------- the API


class TestAuditLogAPI:
    def test_staff_cannot_read_audit_logs(self, staff):
        api = APIClient()
        api.force_authenticate(user=staff)
        assert api.get(LIST_URL).status_code == 403

    def test_admin_can_list_and_filter(self, admin, admin_api):
        make_client()
        acme = make_client(name="Filter Target", email="ft@example.com")
        acme.is_active = False
        acme.save()

        assert admin_api.get(LIST_URL).status_code == 200
        response = admin_api.get(LIST_URL, {"action": AuditLog.Action.SOFT_DELETED})
        assert response.data["count"] == 1
        assert response.data["results"][0]["target_repr"] == str(acme)

    def test_api_is_append_only(self, admin_api):
        acme = make_client()
        entry = AuditLog.objects.get(object_id=acme.pk)
        url = reverse("audit:auditlog-detail", args=[entry.pk])
        assert admin_api.patch(url, {"action": "updated"}).status_code == 405
        assert admin_api.delete(url).status_code == 405
