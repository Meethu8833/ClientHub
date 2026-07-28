# Meeting Scheduler Module

Backend for scheduling and running meetings: a controlled lifecycle, mixed
internal/client attendees with RSVP, denormalized email reminders sent by a
cron command, conflict detection, Minutes of Meeting with action items, and
ICS calendar export. Lives in `apps/meetings`; meetings are registered in the
attachments registry, so notes, documents and the activity timeline all work
on them.

## Concepts

- **Meeting** — one scheduled conversation, optionally tied to a `Client`
  (PROTECT) and/or a `Project` (SET_NULL; the client is derived from the
  project when omitted). **Never deleted** — meeting history is evidence of
  the relationship; a meeting that won't happen is *cancelled*, with reason.
- **Lifecycle (`status`)** — a small state machine:

  ```
             ┌──▶ completed   (→ unlocks minutes & action items)
  scheduled ─┼──▶ cancelled   (requires reason; emails the room)
             └──▶ no_show     (we showed up, they didn't)
  ```

  All three ends are terminal — "reviving" a finished meeting is scheduling
  a new one. `status` is **read-only in every serializer**; it moves only
  through the action endpoints because every move carries side effects.
  DB CheckConstraints pin `completed_at`/`cancelled_at` to their statuses.
  **Rescheduling is not a status**: the meeting stays `scheduled`;
  `rescheduled_count` bumps (and feeds the ICS `SEQUENCE`).
- **Attendees** — `MeetingAttendee`: EITHER an internal `user` OR a client
  `contact`, XOR + per-kind uniqueness DB-enforced. The organizer is
  auto-added (accepted) on creation and can never be removed. `is_required`
  separates people who block the slot from FYI invitees. Users RSVP via
  `POST /meetings/{id}/respond/` (`accepted/declined/tentative`); contacts
  have no login and stay `pending`. A reschedule resets every RSVP except
  the organizer's — an acceptance of Tuesday says nothing about Friday.
- **Conflict detection** — creating/rescheduling/inviting rejects (400,
  listing the clashes) any overlap for *required* internal people. Overlap
  test: `existing.start < new.end AND existing.end > new.start`, only
  against `scheduled` meetings.
- **Reminders** — `MeetingReminder`: offsets in minutes before start
  (default `[1440, 60]`), with `remind_at` **denormalized** (indexed
  absolute time; re-stamped on reschedule, sent rows untouched). The
  `send_meeting_reminders` management command (cron every 1–5 min,
  `--dry-run` supported) emails all attendees for due rows; `sent_at` is
  the idempotency guard (claimed only while NULL — retries safe, no
  double-sends); reminders whose meeting already started are stamped and
  skipped.
- **Minutes of Meeting** — `MeetingMinutes`, OneToOne (at most one
  authoritative record), create-or-update via `PUT /meetings/{id}/minutes/`,
  **only on completed meetings**. `ActionItem` rows (FK to Meeting, not to
  Minutes — follow-ups exist without formal minutes) carry description,
  optional internal `owner`, `due_date`, `is_done`.
- **Calendar integration** — `GET /meetings/{id}/ics/` renders one RFC 5545
  VEVENT (hand-built, CRLF, escaped) importable by Google/Outlook/Apple.
  Stable `UID:meeting-{pk}@clienthub` + `SEQUENCE:{rescheduled_count}` means
  re-imports *update* the event instead of duplicating it. Live two-way sync
  (Google Calendar API/Microsoft Graph via OAuth) is a future integration —
  the export gives interoperability without storing third-party tokens.
- **Emails** — invitation on create, notice on reschedule/cancel, nudges
  from the cron command. All best-effort: failures are logged, never a 500;
  unsent *reminders* retry on the next sweep by design.

## Endpoints

```
/api/v1/meetings/                  list/create/retrieve/patch (no DELETE)
    ?status= &mode= &client= &project= &organizer= &attendee=
    ?scheduled_after= &scheduled_before= &upcoming=true &my=true
    ?search= (title/agenda/client name)  ?ordering=scheduled_start
/api/v1/meetings/{id}/reschedule/  POST {scheduled_start, scheduled_end}
/api/v1/meetings/{id}/cancel/      POST {reason}
/api/v1/meetings/{id}/complete/    POST   (only after start time)
/api/v1/meetings/{id}/no-show/     POST   (only after start time)
/api/v1/meetings/{id}/respond/     POST {response}       any attendee, self
/api/v1/meetings/{id}/attendees/   GET; POST {user_id XOR contact_id, is_required}
/api/v1/meeting-attendees/{id}/    DELETE (flat, §6)
/api/v1/meetings/{id}/minutes/     GET; PUT {content}
/api/v1/meetings/{id}/action-items/ GET; POST {description, owner_id?, due_date?}
/api/v1/action-items/{id}/         PATCH/DELETE (flat)
/api/v1/meetings/{id}/ics/         GET → text/calendar attachment
```

PATCH edits scalars only: times → `/reschedule/` (side effects), people →
attendee endpoints, `status` → lifecycle verbs. Creation additionally takes
`attendee_user_ids`, `attendee_contact_ids`, `reminder_offsets`.

## Permissions

- **Visibility (§8 layer 2, queryset scoping):** admins/managers see all;
  STAFF see meetings they organize **or attend** — out-of-scope meetings
  404 (existence not leaked). Same scope mirrored in the attachments
  registry for notes/documents on meetings.
- **Writes:** organizer or manager/admin (`IsOwnerOrManager`,
  `owner_field="organizer"`) for edit, lifecycle verbs, attendees, minutes,
  action items. **RSVP is each attendee's own** — no organizer permission.
  Action items are also editable by their `owner` (ticking done).

## Cron

```
*/5 * * * *  cd backend && python manage.py send_meeting_reminders
```

## Tests

`apps/meetings/tests/` — scheduling validation + conflicts, lifecycle
boundaries per role, RSVP, reschedule side effects (reminder re-stamp, RSVP
reset), scoping, attendee XOR/dedupe/organizer-guard, minutes/action-item
rules, reminder idempotency + stale skip, ICS shape.
