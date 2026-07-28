"""
Automatic escalation sweep: flag every unfinished, not-yet-escalated ticket
that has blown either SLA deadline.

Why a management command and not code inside a request: SLA breaches happen
while NOBODY is calling the API (3 a.m. on a weekend is exactly when they
happen). Anything time-driven needs a scheduler, and the Django-native shape
for that is a management command run by cron/systemd-timer, e.g.

    */15 * * * *  cd /app && python manage.py escalate_overdue_tickets

--dry-run prints what WOULD be escalated without writing (same idea as the
commit_status dry-runs elsewhere in the stack).
"""

import logging

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from apps.tickets import services
from apps.tickets.models import Ticket

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Escalate unfinished tickets that have breached an SLA deadline."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Report only, change nothing.")

    def handle(self, *args, **options):
        now = timezone.now()
        overdue = Ticket.objects.filter(status__in=Ticket.OPEN_STATUSES, is_escalated=False).filter(
            Q(first_response_at=None, first_response_due_at__lt=now) | Q(resolution_due_at__lt=now)
        )

        count = 0
        for ticket in overdue:
            which = "first response" if ticket.is_first_response_overdue else "resolution"
            if options["dry_run"]:
                self.stdout.write(f"would escalate #{ticket.pk} ({which} SLA breached)")
            else:
                # actor=None = "the system did this" — the timeline shows an
                # escalation with no human attached, which is the truth.
                services.escalate_ticket(
                    ticket=ticket, actor=None, reason=f"Automatic: {which} SLA breached."
                )
                logger.info("Auto-escalated ticket %s (%s SLA breached)", ticket.pk, which)
            count += 1

        verb = "Would escalate" if options["dry_run"] else "Escalated"
        self.stdout.write(self.style.SUCCESS(f"{verb} {count} ticket(s)."))
