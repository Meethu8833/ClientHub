"""
The email-queue CONSUMER. Cron runs it every minute:

    * * * * *  cd /path/backend && python manage.py send_queued_emails

Delivery contract is AT-LEAST-ONCE: a row is only marked SENT after SMTP
accepts it, so a crash between send and save can (rarely) resend one email
— the harmless direction. The opposite guarantee (at-most-once: mark first,
send after) would silently LOSE mail on every crash.

Safe to run from several machines at once: select_for_update(skip_locked)
makes each row claimable by exactly one worker per sweep.
"""

import logging
from datetime import timedelta

from django.core.mail import EmailMessage
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.notifications.models import EmailOutbox

logger = logging.getLogger(__name__)

BATCH_SIZE = 100  # bounded work per run — cron fires again in a minute anyway


class Command(BaseCommand):
    help = "Deliver pending EmailOutbox rows (run from cron every minute)."

    def handle(self, *args, **options):
        sent = failed = 0
        now = timezone.now()

        with transaction.atomic():
            due = (
                EmailOutbox.objects.select_for_update(skip_locked=True)
                .filter(status=EmailOutbox.Status.PENDING, next_attempt_at__lte=now)
                .order_by("next_attempt_at")[:BATCH_SIZE]
            )
            for row in due:
                row.attempts += 1
                try:
                    EmailMessage(subject=row.subject, body=row.body, to=[row.to_email]).send()
                except Exception as exc:  # SMTP down, bad address, timeout…
                    row.last_error = str(exc)[:2000]
                    if row.attempts >= EmailOutbox.MAX_ATTEMPTS:
                        row.status = EmailOutbox.Status.FAILED
                        failed += 1
                        logger.error(
                            "Email #%s to %s failed permanently: %s", row.pk, row.to_email, exc
                        )
                    else:
                        # Exponential backoff: 2, 4, 8, 16 min between tries —
                        # transient outages get room to recover.
                        delay = timedelta(minutes=2**row.attempts)
                        row.next_attempt_at = timezone.now() + delay
                        logger.warning(
                            "Email #%s attempt %s failed, retrying in %s: %s",
                            row.pk,
                            row.attempts,
                            delay,
                            exc,
                        )
                else:
                    row.status = EmailOutbox.Status.SENT
                    row.sent_at = timezone.now()
                    sent += 1
                row.save()

        self.stdout.write(f"sent={sent} permanently_failed={failed}")
