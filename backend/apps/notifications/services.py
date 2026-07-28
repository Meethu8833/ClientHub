"""
The single producer-facing entry point: notify().

Every other app raises notifications through this ONE function and never
touches the notification tables directly. That seam is the whole design:
producers describe the EVENT (who, what, about which object); this module
owns HOW it is delivered (which channels, preferences, queuing, retries).
Swapping the email queue for Celery or the push stub for real FCM later
changes this file only — no producer moves.
"""

import logging

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from .models import (
    EmailOutbox,
    Notification,
    NotificationPreference,
    PushDevice,
)

logger = logging.getLogger(__name__)


def notify(*, recipients, category, title, body="", actor=None, target=None) -> list[Notification]:
    """
    Fan one event out to many users across their enabled channels.

    recipients  iterable of User (a single user works too: pass [user])
    category    NotificationCategory value — the preference-toggle unit
    title       short rendered sentence ("Maria assigned you ticket #42")
    body        optional longer text (email body paragraph)
    actor       who caused it; actors are never notified about their own
                actions (nobody wants "you assigned yourself a ticket")
    target      optional model instance the event is about (deep-link)

    Returns the created in-app Notification rows.

    Runs inside the caller's transaction: if the business write rolls
    back, the notification rows and queued emails vanish with it — you
    can never notify about something that didn't happen. Push (an
    external call) is deferred with on_commit for the same reason.
    """
    content_type = ContentType.objects.get_for_model(target) if target is not None else None
    prefs = _preferences_for(recipients, category)

    created: list[Notification] = []
    for user in recipients:
        if actor is not None and user.pk == actor.pk:
            continue  # never notify someone about their own action
        pref = prefs.get(user.pk)

        if pref is None or pref.in_app_enabled:
            created.append(
                Notification.objects.create(
                    recipient=user,
                    actor=actor,
                    category=category,
                    title=title,
                    body=body,
                    content_type=content_type,
                    object_id=target.pk if target is not None else None,
                )
            )

        if pref is None or pref.email_enabled:
            EmailOutbox.objects.create(
                to_email=user.email,
                subject=title,
                body=body or title,
                next_attempt_at=timezone.now(),  # eligible immediately
            )

        if pref is None or pref.push_enabled:
            # Capture the pk, not the user object: by the time on_commit
            # fires, this loop is long gone.
            transaction.on_commit(
                lambda user_id=user.pk, t=title, b=body: _push_to_user(user_id, t, b)
            )

    return created


def _preferences_for(recipients, category) -> dict[int, NotificationPreference]:
    """
    One query for every recipient's switchboard row for this category.
    Missing rows simply aren't in the dict — notify() treats absence as
    "all channels on" (the lazy-row design from models.py).
    """
    rows = NotificationPreference.objects.filter(
        user__in=[u.pk for u in recipients], category=category
    )
    return {p.user_id: p for p in rows}


def _push_to_user(user_id: int, title: str, body: str) -> None:
    """
    Deliver a push message to every device the user registered.

    DEV STUB: logs instead of calling a push provider — the seam where
    real delivery plugs in. With Firebase Cloud Messaging this becomes:
    build a firebase_admin.messaging.MulticastMessage from the tokens,
    send_each_for_multicast(), and DELETE PushDevice rows whose token the
    provider reports as expired/unregistered (tokens rot when the app is
    reinstalled or permission is revoked — pruning them is mandatory
    hygiene, not an optimization).
    """
    tokens = list(PushDevice.objects.filter(user_id=user_id).values_list("token", flat=True))
    if not tokens:
        return
    logger.info("PUSH to user %s (%d device(s)): %s — %s", user_id, len(tokens), title, body)
