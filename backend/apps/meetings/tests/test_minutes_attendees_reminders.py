"""
Attendee management (XOR, dedupe, organizer guard), Minutes of Meeting
(completed-only, create-or-update), action items (flat PATCH scope), and the
reminder cron command (idempotency, stale skip).
"""

from datetime import timedelta

import pytest
from django.core import mail
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client, Contact
from apps.meetings.models import Meeting, MeetingAttendee, MeetingReminder

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager():
    return User.objects.create_user(email="mgr@x.com", password=PASSWORD, role=User.Role.MANAGER)


@pytest.fixture
def staff():
    return User.objects.create_user(email="staff@x.com", password=PASSWORD, role=User.Role.STAFF)


def api_for(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def staff_api(staff):
    return api_for(staff)


def in_hours(h):
    return timezone.now() + timedelta(hours=h)


def make_meeting(organizer, start_h=2, end_h=3, **kw):
    meeting = Meeting.objects.create(
        title="Sync",
        organizer=organizer,
        scheduled_start=in_hours(start_h),
        scheduled_end=in_hours(end_h),
        **kw,
    )
    MeetingAttendee.objects.create(
        meeting=meeting, user=organizer, response=MeetingAttendee.Response.ACCEPTED
    )
    return meeting


def completed_meeting(organizer):
    meeting = make_meeting(organizer, start_h=-3, end_h=-2)
    api_for(organizer).post(reverse("meetings:meeting-complete", args=[meeting.pk]))
    meeting.refresh_from_db()
    return meeting


# --- attendees ---------------------------------------------------------------


def test_add_and_remove_attendee(staff_api, staff, manager):
    meeting = make_meeting(staff)
    attendees_url = reverse("meetings:meeting-attendees", args=[meeting.pk])

    res = staff_api.post(attendees_url, {"user_id": manager.pk}, format="json")
    assert res.status_code == 201
    assert res.data["kind"] == "user"
    # duplicate invite → clean 400, not IntegrityError
    assert staff_api.post(attendees_url, {"user_id": manager.pk}, format="json").status_code == 400

    row_id = res.data["id"]
    res = staff_api.delete(reverse("meetings:meeting-attendee-detail", args=[row_id]))
    assert res.status_code == 204
    assert not meeting.attendees.filter(user=manager).exists()


def test_attendee_xor_body(staff_api, staff, manager):
    meeting = make_meeting(staff)
    attendees_url = reverse("meetings:meeting-attendees", args=[meeting.pk])
    assert staff_api.post(attendees_url, {}, format="json").status_code == 400
    acme = Client.objects.create(name="Acme")
    ravi = Contact.objects.create(client=acme, name="Ravi")
    body = {"user_id": manager.pk, "contact_id": ravi.pk}
    assert staff_api.post(attendees_url, body, format="json").status_code == 400


def test_contact_attendee_requires_matching_client(staff_api, staff):
    acme = Client.objects.create(name="Acme")
    ravi = Contact.objects.create(client=acme, name="Ravi")
    meeting = make_meeting(staff)  # no client on the meeting
    attendees_url = reverse("meetings:meeting-attendees", args=[meeting.pk])
    assert staff_api.post(attendees_url, {"contact_id": ravi.pk}, format="json").status_code == 400


def test_organizer_row_cannot_be_removed(staff_api, staff):
    meeting = make_meeting(staff)
    row = meeting.attendees.get(user=staff)
    res = staff_api.delete(reverse("meetings:meeting-attendee-detail", args=[row.pk]))
    assert res.status_code == 400


def test_non_organizer_staff_cannot_manage_attendees(staff, manager):
    meeting = make_meeting(manager)
    MeetingAttendee.objects.create(meeting=meeting, user=staff)
    attendees_url = reverse("meetings:meeting-attendees", args=[meeting.pk])
    # visible to the attendee (GET ok) …
    assert api_for(staff).get(attendees_url).status_code == 200
    # … but the invite list is the organizer's (or a manager's) to change
    res = api_for(staff).post(attendees_url, {"user_id": staff.pk}, format="json")
    assert res.status_code == 403


# --- minutes of meeting ------------------------------------------------------


def test_minutes_only_on_completed(staff_api, staff):
    meeting = make_meeting(staff)  # still scheduled
    minutes_url = reverse("meetings:meeting-minutes", args=[meeting.pk])
    assert staff_api.put(minutes_url, {"content": "…"}, format="json").status_code == 400
    assert staff_api.get(minutes_url).status_code == 404


def test_minutes_create_then_update(staff_api, staff):
    meeting = completed_meeting(staff)
    minutes_url = reverse("meetings:meeting-minutes", args=[meeting.pk])

    res = staff_api.put(minutes_url, {"content": "Decided X."}, format="json")
    assert res.status_code == 200
    assert res.data["recorded_by"]["id"] == staff.pk

    res = staff_api.put(minutes_url, {"content": "Decided X and Y."}, format="json")
    assert res.status_code == 200
    assert meeting.minutes.content == "Decided X and Y."  # updated, not duplicated
    assert staff_api.get(minutes_url).data["content"] == "Decided X and Y."


# --- action items ------------------------------------------------------------


def test_action_items_flow(staff_api, staff, manager):
    meeting = completed_meeting(staff)
    items_url = reverse("meetings:meeting-action-items", args=[meeting.pk])

    res = staff_api.post(
        items_url, {"description": "Send revised quote", "owner_id": manager.pk}, format="json"
    )
    assert res.status_code == 201
    item_id = res.data["id"]
    assert res.data["owner"]["id"] == manager.pk

    # the OWNER can tick it done even though they don't organize the meeting
    res = api_for(manager).patch(
        reverse("meetings:action-item-detail", args=[item_id]), {"is_done": True}, format="json"
    )
    assert res.status_code == 200
    assert res.data["is_done"] is True

    assert len(staff_api.get(items_url).data) == 1


def test_action_items_only_on_completed(staff_api, staff):
    meeting = make_meeting(staff)
    items_url = reverse("meetings:meeting-action-items", args=[meeting.pk])
    assert staff_api.post(items_url, {"description": "X"}, format="json").status_code == 400


# --- reminder command --------------------------------------------------------


def test_send_meeting_reminders_is_idempotent(staff):
    meeting = make_meeting(staff, start_h=1, end_h=2)
    # offset 120min > 60min-away start ⇒ remind_at is in the past ⇒ due now
    MeetingReminder.objects.create(
        meeting=meeting,
        offset_minutes=120,
        remind_at=meeting.scheduled_start - timedelta(minutes=120),
    )
    mail.outbox.clear()

    call_command("send_meeting_reminders")
    assert len(mail.outbox) == 1
    assert "Reminder" in mail.outbox[0].subject
    assert mail.outbox[0].to == ["staff@x.com"]

    call_command("send_meeting_reminders")  # second run: nothing left to send
    assert len(mail.outbox) == 1


def test_stale_reminder_skipped_not_sent(staff):
    meeting = make_meeting(staff, start_h=-1, end_h=1)  # already started
    reminder = MeetingReminder.objects.create(
        meeting=meeting, offset_minutes=60, remind_at=in_hours(-2)
    )
    mail.outbox.clear()
    call_command("send_meeting_reminders")
    reminder.refresh_from_db()
    assert reminder.sent_at is not None  # stamped so it never retries
    assert len(mail.outbox) == 0  # …but no pointless email


def test_cancelled_meeting_sends_no_reminder(staff):
    meeting = make_meeting(staff, start_h=1, end_h=2)
    MeetingReminder.objects.create(meeting=meeting, offset_minutes=120, remind_at=in_hours(-1))
    Meeting.objects.filter(pk=meeting.pk).update(
        status=Meeting.Status.CANCELLED, cancelled_at=timezone.now()
    )
    mail.outbox.clear()
    call_command("send_meeting_reminders")
    assert len(mail.outbox) == 0
