"""
Meeting API tests: scheduling (validation, conflicts, auto-attendee,
reminders, invites), the lifecycle state machine, RSVP, rescheduling side
effects, per-role visibility scoping and permission boundaries, ICS export.
"""

from datetime import timedelta

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.clients.models import Client, Contact
from apps.meetings.models import Meeting, MeetingAttendee

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db

LIST_URL = reverse("meetings:meeting-list")


def url(meeting_id, action=None):
    if action:
        return reverse(f"meetings:meeting-{action}", args=[meeting_id])
    return reverse("meetings:meeting-detail", args=[meeting_id])


# --- fixtures ---------------------------------------------------------------


@pytest.fixture
def manager():
    return User.objects.create_user(email="mgr@x.com", password=PASSWORD, role=User.Role.MANAGER)


@pytest.fixture
def staff():
    return User.objects.create_user(email="staff@x.com", password=PASSWORD, role=User.Role.STAFF)


@pytest.fixture
def staff2():
    return User.objects.create_user(email="staff2@x.com", password=PASSWORD, role=User.Role.STAFF)


def api_for(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def manager_api(manager):
    return api_for(manager)


@pytest.fixture
def staff_api(staff):
    return api_for(staff)


@pytest.fixture
def acme():
    return Client.objects.create(name="Acme Fintech")


@pytest.fixture
def ravi(acme):
    return Contact.objects.create(client=acme, name="Ravi", email="ravi@acme.com")


def in_hours(h):
    return timezone.now() + timedelta(hours=h)


def payload(**overrides):
    body = {
        "title": "Kickoff call",
        "scheduled_start": in_hours(2).isoformat(),
        "scheduled_end": in_hours(3).isoformat(),
    }
    body.update(overrides)
    return body


def make_meeting(organizer, start_h=2, end_h=3, **kw):
    """ORM shortcut for tests that need a meeting in an arbitrary time/state."""
    meeting = Meeting.objects.create(
        title=kw.pop("title", "Standing sync"),
        organizer=organizer,
        scheduled_start=in_hours(start_h),
        scheduled_end=in_hours(end_h),
        **kw,
    )
    MeetingAttendee.objects.create(
        meeting=meeting, user=organizer, response=MeetingAttendee.Response.ACCEPTED
    )
    return meeting


# --- creation ---------------------------------------------------------------


def test_create_meeting_full_shape(staff_api, staff, staff2, acme, ravi):
    res = staff_api.post(
        LIST_URL,
        payload(
            client_id=acme.pk,
            agenda="Scope and timeline",
            attendee_user_ids=[staff2.pk],
            attendee_contact_ids=[ravi.pk],
            reminder_offsets=[60],
        ),
        format="json",
    )
    assert res.status_code == 201, res.data
    data = res.data
    assert data["status"] == "scheduled"
    assert data["organizer"]["id"] == staff.pk
    # organizer auto-attends (accepted) + invited user + invited contact
    assert data["attendee_count"] == 3
    organizer_row = next(a for a in data["attendees"] if a["person"]["id"] == staff.pk)
    assert organizer_row["response"] == "accepted"
    # reminder stamped at start - 60min
    assert len(data["reminders"]) == 1
    assert data["reminders"][0]["offset_minutes"] == 60
    # timeline opened + invitation email to all three
    meeting = Meeting.objects.get(pk=data["id"])
    assert Activity.objects.filter(object_id=meeting.pk, verb="created").exists()
    assert len(mail.outbox) == 1
    assert set(mail.outbox[0].to) == {"staff@x.com", "staff2@x.com", "ravi@acme.com"}


def test_create_rejects_end_before_start(staff_api):
    res = staff_api.post(
        LIST_URL,
        payload(scheduled_start=in_hours(3).isoformat(), scheduled_end=in_hours(2).isoformat()),
        format="json",
    )
    assert res.status_code == 400
    assert "scheduled_end" in res.data


def test_create_rejects_past_start(staff_api):
    res = staff_api.post(
        LIST_URL,
        payload(scheduled_start=in_hours(-2).isoformat(), scheduled_end=in_hours(1).isoformat()),
        format="json",
    )
    assert res.status_code == 400
    assert "scheduled_start" in res.data


def test_create_rejects_foreign_contact(staff_api, acme, ravi):
    other = Client.objects.create(name="Beta Corp")
    res = staff_api.post(
        LIST_URL, payload(client_id=other.pk, attendee_contact_ids=[ravi.pk]), format="json"
    )
    assert res.status_code == 400
    assert "attendee_contact_ids" in res.data


def test_create_rejects_organizer_double_booking(staff_api, staff):
    make_meeting(staff, start_h=2, end_h=3)
    res = staff_api.post(LIST_URL, payload(), format="json")  # same 2h-3h slot
    assert res.status_code == 400
    assert "scheduled_start" in res.data


def test_optional_attendee_does_not_block(staff_api, staff, staff2):
    busy = make_meeting(staff2, start_h=2, end_h=3)
    # staff2 is only OPTIONAL in the new meeting — double-booking allowed
    MeetingAttendee.objects.filter(meeting=busy).update(is_required=True)
    res = staff_api.post(LIST_URL, payload(attendee_user_ids=[staff2.pk]), format="json")
    # staff2 organizes the busy meeting → required there → conflict
    assert res.status_code == 400


# --- visibility scoping (§8 layer 2) ---------------------------------------


def test_staff_sees_only_own_or_invited(staff_api, staff, staff2, manager):
    mine = make_meeting(staff)
    invited = make_meeting(manager, start_h=5, end_h=6)
    MeetingAttendee.objects.create(meeting=invited, user=staff)
    foreign = make_meeting(staff2, start_h=8, end_h=9)

    ids = {m["id"] for m in staff_api.get(LIST_URL).data["results"]}
    assert ids == {mine.pk, invited.pk}
    assert staff_api.get(url(foreign.pk)).status_code == 404  # not 403 — don't leak


def test_manager_sees_everything(manager_api, staff, staff2):
    make_meeting(staff)
    make_meeting(staff2, start_h=5, end_h=6)
    assert manager_api.get(LIST_URL).data["count"] == 2


# --- edit permissions --------------------------------------------------------


def test_attendee_cannot_edit_someone_elses_meeting(staff, staff2, manager):
    meeting = make_meeting(manager)
    MeetingAttendee.objects.create(meeting=meeting, user=staff)
    res = api_for(staff).patch(url(meeting.pk), {"title": "Hijacked"}, format="json")
    assert res.status_code == 403  # visible (attendee) but not the owner


def test_patch_time_is_rejected_use_reschedule(staff_api, staff):
    meeting = make_meeting(staff)
    res = staff_api.patch(
        url(meeting.pk), {"scheduled_start": in_hours(4).isoformat()}, format="json"
    )
    assert res.status_code == 400
    assert "scheduled_start" in res.data


# --- lifecycle ---------------------------------------------------------------


def test_cancel_requires_reason_and_stamps(staff_api, staff):
    meeting = make_meeting(staff)
    assert staff_api.post(url(meeting.pk, "cancel"), {}, format="json").status_code == 400

    mail.outbox.clear()
    res = staff_api.post(url(meeting.pk, "cancel"), {"reason": "Client away"}, format="json")
    assert res.status_code == 200
    assert res.data["status"] == "cancelled"
    assert res.data["cancel_reason"] == "Client away"
    assert res.data["cancelled_at"] is not None
    assert len(mail.outbox) == 1  # cancellation notice

    # terminal: no second cancel, no complete
    res = staff_api.post(url(meeting.pk, "cancel"), {"reason": "again"}, format="json")
    assert res.status_code == 400


def test_complete_only_after_start(staff_api, staff):
    future = make_meeting(staff)
    assert staff_api.post(url(future.pk, "complete")).status_code == 400

    past = make_meeting(staff, start_h=-3, end_h=-2)
    res = staff_api.post(url(past.pk, "complete"))
    assert res.status_code == 200
    assert res.data["status"] == "completed"
    assert res.data["completed_at"] is not None


def test_no_show_after_start(staff_api, staff):
    past = make_meeting(staff, start_h=-3, end_h=-2)
    res = staff_api.post(url(past.pk, "no-show"))
    assert res.status_code == 200
    assert res.data["status"] == "no_show"


# --- RSVP --------------------------------------------------------------------


def test_attendee_can_respond(staff, manager):
    meeting = make_meeting(manager)
    MeetingAttendee.objects.create(meeting=meeting, user=staff)
    res = api_for(staff).post(url(meeting.pk, "respond"), {"response": "accepted"}, format="json")
    assert res.status_code == 200
    assert res.data["response"] == "accepted"
    assert res.data["responded_at"] is not None


def test_non_attendee_cannot_respond(manager_api, staff):
    meeting = make_meeting(staff)  # manager sees it, but isn't invited
    res = manager_api.post(url(meeting.pk, "respond"), {"response": "accepted"}, format="json")
    assert res.status_code == 400


# --- reschedule --------------------------------------------------------------


def test_reschedule_side_effects(staff_api, staff, staff2):
    res = staff_api.post(
        LIST_URL, payload(attendee_user_ids=[staff2.pk], reminder_offsets=[60]), format="json"
    )
    meeting = Meeting.objects.get(pk=res.data["id"])
    meeting.attendees.filter(user=staff2).update(response=MeetingAttendee.Response.ACCEPTED)
    mail.outbox.clear()

    res = staff_api.post(
        url(meeting.pk, "reschedule"),
        {"scheduled_start": in_hours(26).isoformat(), "scheduled_end": in_hours(27).isoformat()},
        format="json",
    )
    assert res.status_code == 200, res.data
    assert res.data["rescheduled_count"] == 1
    # reminder re-stamped against the NEW start
    reminder = meeting.reminders.get()
    assert abs((reminder.remind_at - (in_hours(26) - timedelta(minutes=60))).total_seconds()) < 5
    # invitee RSVP reset to pending; organizer stays accepted
    assert meeting.attendees.get(user=staff2).response == "pending"
    assert meeting.attendees.get(user=staff).response == "accepted"
    # everyone notified + timeline row
    assert len(mail.outbox) == 1
    assert Activity.objects.filter(object_id=meeting.pk, verb="rescheduled").exists()


def test_reschedule_rejects_conflict(staff_api, staff):
    make_meeting(staff, start_h=10, end_h=11)
    movable = make_meeting(staff, start_h=2, end_h=3)
    res = staff_api.post(
        url(movable.pk, "reschedule"),
        {
            "scheduled_start": in_hours(10).isoformat(),
            "scheduled_end": in_hours(11).isoformat(),
        },
        format="json",
    )
    assert res.status_code == 400


# --- filters -----------------------------------------------------------------


def test_upcoming_and_attendee_filters(manager_api, staff, manager):
    upcoming = make_meeting(manager, start_h=2, end_h=3)
    past = make_meeting(manager, start_h=-3, end_h=-2, title="Old sync")
    MeetingAttendee.objects.create(meeting=past, user=staff)

    res = manager_api.get(LIST_URL, {"upcoming": "true"})
    assert [m["id"] for m in res.data["results"]] == [upcoming.pk]

    res = manager_api.get(LIST_URL, {"attendee": staff.pk})
    assert [m["id"] for m in res.data["results"]] == [past.pk]


# --- ICS export --------------------------------------------------------------


def test_ics_download(staff_api, staff):
    meeting = make_meeting(staff, title="Design review")
    res = staff_api.get(url(meeting.pk, "ics"))
    assert res.status_code == 200
    assert res["Content-Type"].startswith("text/calendar")
    body = res.content.decode()
    assert "BEGIN:VCALENDAR" in body
    assert f"UID:meeting-{meeting.pk}@clienthub" in body
    assert "SUMMARY:Design review" in body
