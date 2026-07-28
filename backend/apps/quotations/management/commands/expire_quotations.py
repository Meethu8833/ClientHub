"""
Nightly sweep: SENT quotations past their valid_until become EXPIRED.

Run by cron (same deployment pattern as escalate_overdue_tickets):
    python manage.py expire_quotations

The sweep is the system acting (actor=None on the history row). The API is
still safe in the gap between runs — accept() checks is_expired live — but
the sweep keeps list screens and reports truthful without every reader
having to re-derive expiry.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.quotations import services
from apps.quotations.models import Quotation


class Command(BaseCommand):
    help = "Mark sent quotations past their validity date as expired."

    def handle(self, *args, **options):
        lapsed = Quotation.objects.filter(
            status=Quotation.Status.SENT, valid_until__lt=timezone.localdate()
        )
        count = 0
        for quotation in lapsed:
            services.expire_quotation(quotation=quotation)
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Expired {count} quotation(s)."))
