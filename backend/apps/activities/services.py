"""
The one way to write history rows. Every app calls activities.services.record()
instead of creating Activity objects directly, so the shape of a history event
is decided in exactly one place.
"""

from .models import Activity


def record(*, actor, target, verb, changes=None) -> Activity:
    """
    Append one event to `target`'s timeline.

    Keyword-only arguments (the `*`) on purpose: record(user, project, ...) at
    a call site says nothing — record(actor=user, target=project, verb=...) does.
    """
    return Activity.objects.create(
        actor=actor,
        content_object=target,
        verb=verb,
        changes=changes or {},
    )
