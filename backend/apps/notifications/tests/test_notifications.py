"""
Notification system tests: the notify() fan-out (preference gating,
self-notification skip, outbox queuing), the queue worker (delivery, retry
backoff, permanent failure), the user-scoped API (list/unread/mark-read),
the preference switchboard, push-device registration/upsert, and the ticket
assignment integration.
"""

from datetime import timedelta
from unittest import mock

import pytest
from django.core import mail
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.notifications.models import (
    EmailOutbox,
    Notification,
    NotificationCategory,
    NotificationPreference,
    PushDevice,
)
from apps.notifications.services import notify

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db

LIST_URL = reverse("notifications:notification-list")
PREFS_URL = reverse("notifications:notification-preference-list")
DEVICES_URL = reverse("notifications:push-device-list")


@pytest.fixture
def manager():
    return User.objects.create_user(email="mgr@x.com", password=PASSWORD, role=User.Role.MANAGER)


@pytest.fixture
def staff():
    return User.objects.create_user(email="staff@x.com", password=PASSWORD, role=User.Role.STAFF)


@pytest.fixture
def api(staff):
    client = APIClient()
    client.force_authenticate(staff)
    return client


# --- notify() service -------------------------------------------------------


class TestNotifyService:
    def test_creates_in_app_row_and_queues_email(self, manager, staff):
        created = notify(
            recipients=[staff],
            category=NotificationCategory.TICKET,
            title="You were assigned ticket #1",
            body="Details here.",
            actor=manager,
        )

        assert len(created) == 1
        n = created[0]
        assert n.recipient == staff and n.actor == manager and not n.is_read

        outbox = EmailOutbox.objects.get()
        assert outbox.to_email == staff.email
        assert outbox.status == EmailOutbox.Status.PENDING
        assert outbox.subject == "You were assigned ticket #1"
        # Queued, NOT sent — nothing hit the email backend yet.
        assert len(mail.outbox) == 0

    def test_actor_is_never_notified_about_own_action(self, staff):
        created = notify(
            recipients=[staff],
            category=NotificationCategory.TICKET,
            title="You assigned yourself",
            actor=staff,
        )
        assert created == []
        assert Notification.objects.count() == 0
        assert EmailOutbox.objects.count() == 0

    def test_preferences_gate_each_channel(self, manager, staff):
        NotificationPreference.objects.create(
            user=staff,
            category=NotificationCategory.TICKET,
            in_app_enabled=True,
            email_enabled=False,
        )
        notify(
            recipients=[staff],
            category=NotificationCategory.TICKET,
            title="No email please",
            actor=manager,
        )
        assert Notification.objects.filter(recipient=staff).count() == 1
        assert EmailOutbox.objects.count() == 0

    def test_other_categories_unaffected_by_a_preference(self, manager, staff):
        NotificationPreference.objects.create(
            user=staff, category=NotificationCategory.TICKET, email_enabled=False
        )
        notify(
            recipients=[staff],
            category=NotificationCategory.MEETING,  # different category → defaults
            title="Meeting soon",
            actor=manager,
        )
        assert EmailOutbox.objects.count() == 1


# --- the email queue worker -------------------------------------------------


class TestSendQueuedEmails:
    def _queue(self, **overrides):
        defaults = dict(
            to_email="staff@x.com",
            subject="Hello",
            body="World",
            next_attempt_at=timezone.now(),
        )
        defaults.update(overrides)
        return EmailOutbox.objects.create(**defaults)

    def test_sends_due_pending_rows(self):
        row = self._queue()
        call_command("send_queued_emails")
        row.refresh_from_db()
        assert row.status == EmailOutbox.Status.SENT
        assert row.sent_at is not None and row.attempts == 1
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["staff@x.com"]

    def test_skips_rows_not_yet_due(self):
        row = self._queue(next_attempt_at=timezone.now() + timedelta(minutes=30))
        call_command("send_queued_emails")
        row.refresh_from_db()
        assert row.status == EmailOutbox.Status.PENDING
        assert len(mail.outbox) == 0

    def test_failure_reschedules_with_backoff(self):
        row = self._queue()
        with mock.patch(
            "apps.notifications.management.commands.send_queued_emails.EmailMessage.send",
            side_effect=OSError("smtp down"),
        ):
            call_command("send_queued_emails")
        row.refresh_from_db()
        assert row.status == EmailOutbox.Status.PENDING  # will retry
        assert row.attempts == 1
        assert "smtp down" in row.last_error
        assert row.next_attempt_at > timezone.now() + timedelta(minutes=1)

    def test_gives_up_after_max_attempts(self):
        row = self._queue(attempts=EmailOutbox.MAX_ATTEMPTS - 1)
        with mock.patch(
            "apps.notifications.management.commands.send_queued_emails.EmailMessage.send",
            side_effect=OSError("smtp down"),
        ):
            call_command("send_queued_emails")
        row.refresh_from_db()
        assert row.status == EmailOutbox.Status.FAILED

    def test_already_sent_rows_are_never_resent(self):
        self._queue(status=EmailOutbox.Status.SENT, sent_at=timezone.now())
        call_command("send_queued_emails")
        assert len(mail.outbox) == 0


# --- notification API -------------------------------------------------------


class TestNotificationApi:
    def test_user_sees_only_own_notifications(self, api, manager, staff):
        notify(recipients=[staff], category=NotificationCategory.TICKET, title="Yours")
        notify(recipients=[manager], category=NotificationCategory.TICKET, title="Not yours")

        res = api.get(LIST_URL)
        assert res.status_code == 200
        titles = [n["title"] for n in res.data["results"]]
        assert titles == ["Yours"]

    def test_foreign_notification_404s_not_403s(self, api, manager):
        (other,) = notify(
            recipients=[manager], category=NotificationCategory.TICKET, title="Not yours"
        )
        res = api.post(reverse("notifications:notification-read", args=[other.pk]))
        assert res.status_code == 404  # scoping hides existence (§8)

    def test_unread_filter_and_count(self, api, staff):
        a, b = notify(
            recipients=[staff], category=NotificationCategory.TICKET, title="One"
        ) + notify(recipients=[staff], category=NotificationCategory.TICKET, title="Two")
        a.read_at = timezone.now()
        a.save()

        res = api.get(LIST_URL, {"unread": "true"})
        assert [n["id"] for n in res.data["results"]] == [b.pk]

        res = api.get(reverse("notifications:notification-unread-count"))
        assert res.data == {"unread": 1}

    def test_mark_read_is_idempotent(self, api, staff):
        (n,) = notify(recipients=[staff], category=NotificationCategory.TICKET, title="Hi")
        url = reverse("notifications:notification-read", args=[n.pk])

        res = api.post(url)
        assert res.status_code == 200 and res.data["is_read"] is True
        first_read_at = Notification.objects.get(pk=n.pk).read_at

        api.post(url)  # second click
        assert Notification.objects.get(pk=n.pk).read_at == first_read_at

    def test_mark_all_read(self, api, staff):
        notify(recipients=[staff], category=NotificationCategory.TICKET, title="One")
        notify(recipients=[staff], category=NotificationCategory.MEETING, title="Two")

        res = api.post(reverse("notifications:notification-mark-all-read"))
        assert res.data == {"marked_read": 2}
        assert not Notification.objects.filter(recipient=staff, read_at=None).exists()

    def test_notifications_cannot_be_created_via_api(self, api):
        res = api.post(LIST_URL, {"title": "forged"})
        assert res.status_code == 405  # no create route — server-generated only


# --- preferences API --------------------------------------------------------


class TestPreferencesApi:
    def test_list_returns_full_matrix_with_defaults(self, api):
        res = api.get(PREFS_URL)
        assert res.status_code == 200
        assert {row["category"] for row in res.data} == set(NotificationCategory.values)
        assert all(row["email_enabled"] for row in res.data)

    def test_patch_flips_a_switch(self, api, staff):
        url = reverse(
            "notifications:notification-preference-detail", args=[NotificationCategory.TICKET]
        )
        res = api.patch(url, {"email_enabled": False})
        assert res.status_code == 200 and res.data["email_enabled"] is False

        pref = NotificationPreference.objects.get(user=staff, category=NotificationCategory.TICKET)
        assert pref.email_enabled is False and pref.in_app_enabled is True


# --- push devices API -------------------------------------------------------


class TestPushDevicesApi:
    def test_register_and_list(self, api, staff):
        res = api.post(DEVICES_URL, {"token": "tok-abc", "platform": "web"})
        assert res.status_code == 201
        assert PushDevice.objects.get(token="tok-abc").user == staff

        res = api.get(DEVICES_URL)
        assert [d["token"] for d in res.data["results"]] == ["tok-abc"]

    def test_reregistering_same_token_upserts_not_duplicates(self, api):
        api.post(DEVICES_URL, {"token": "tok-abc", "platform": "web"})
        res = api.post(DEVICES_URL, {"token": "tok-abc", "platform": "web"})
        assert res.status_code == 200  # refreshed, not created
        assert PushDevice.objects.filter(token="tok-abc").count() == 1

    def test_token_changes_owner_on_new_login(self, api, manager, staff):
        PushDevice.objects.create(user=manager, token="tok-shared")
        api.post(DEVICES_URL, {"token": "tok-shared", "platform": "web"})
        assert PushDevice.objects.get(token="tok-shared").user == staff

    def test_unregister(self, api, staff):
        device = PushDevice.objects.create(user=staff, token="tok-abc")
        res = api.delete(reverse("notifications:push-device-detail", args=[device.pk]))
        assert res.status_code == 204
        assert PushDevice.objects.count() == 0


# --- ticket assignment integration ------------------------------------------


class TestTicketAssignmentNotifies:
    @staticmethod
    def _make_ticket(manager):
        from apps.clients.models import Client
        from apps.tickets.models import Ticket, TicketCategory
        from apps.tickets.services import create_ticket

        client_ = Client.objects.create(name="Acme", account_manager=manager)
        category = TicketCategory.objects.create(name="Bug")
        ticket = Ticket(client=client_, category=category, subject="Login broken", description="…")
        return create_ticket(ticket=ticket, actor=manager)

    def test_assignee_gets_notified(self, manager, staff):
        from apps.tickets.services import assign_ticket

        ticket = self._make_ticket(manager)
        assign_ticket(ticket=ticket, assignee=staff, actor=manager)

        n = Notification.objects.get(recipient=staff)
        assert n.category == NotificationCategory.TICKET
        assert "Login broken" in n.title
        assert n.target == ticket
        assert EmailOutbox.objects.filter(to_email=staff.email).exists()

    def test_self_claim_does_not_notify(self, manager, staff):
        from apps.tickets.services import assign_ticket

        ticket = self._make_ticket(manager)
        assign_ticket(ticket=ticket, assignee=manager, actor=manager)
        assert Notification.objects.count() == 0
