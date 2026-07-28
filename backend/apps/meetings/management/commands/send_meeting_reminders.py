"""
The reminder sweep — run by cron (`* * * * * manage.py send_meeting_reminders`
or every 5 minutes; the remind_at granularity is minutes anyway).

Why a cron command and not "send when creating the meeting": the send moment
is in the FUTURE. A web request cannot sleep until then, so something outside
the request/response cycle must wake up, ask "which nudges are due?", and
send them. This project has no Celery; a cron'd management command is the
simplest correct scheduler. `sent_at` is the idempotency guard: rows are
claimed only while NULL, so overlapping runs or retries never double-send.
"""

import logging

from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.meetings.models import Meeting, MeetingReminder
from apps.meetings.services import _when_line, attendee_emails

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Send due, unsent meeting reminders (cron)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be sent without sending or stamping anything.",
        )

    def handle(self, *args, **options):
        now = timezone.now()
        due = MeetingReminder.objects.filter(
            sent_at__isnull=True,
            remind_at__lte=now,
            meeting__status=Meeting.Status.SCHEDULED,
        ).select_related("meeting", "meeting__organizer")

        sent = skipped = 0
        for reminder in due:
            meeting = reminder.meeting
            # The moment has passed entirely — a "starts in an hour" mail
            # after the start would be noise. Stamp it so it never retries.
            if meeting.scheduled_start <= now:
                if not options["dry_run"]:
                    reminder.sent_at = now
                    reminder.save(update_fields=["sent_at", "updated_at"])
                skipped += 1
                continue

            recipients = attendee_emails(meeting)
            if options["dry_run"]:
                self.stdout.write(f"Would remind {len(recipients)} people: {meeting}")
                sent += 1
                continue

            try:
                if recipients:
                    EmailMessage(
                        subject=f"Reminder: {meeting.title} at {meeting.scheduled_start:%H:%M}",
                        body=(
                            f"'{meeting.title}' starts soon.\n\n"
                            f"When: {_when_line(meeting)}\n"
                            f"Agenda:\n{meeting.agenda or '(none)'}"
                        ),
                        to=recipients,
                    ).send()
            except Exception:  # noqa: BLE001 — leave sent_at NULL → retried next run
                logger.exception("Reminder %s failed; will retry next run", reminder.pk)
                continue

            reminder.sent_at = timezone.now()
            reminder.save(update_fields=["sent_at", "updated_at"])
            sent += 1

        self.stdout.write(self.style.SUCCESS(f"Reminders sent: {sent}, stale skipped: {skipped}"))
