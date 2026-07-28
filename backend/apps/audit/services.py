"""
The one way to write an audit row (same rule as activities.services.record):
every caller goes through log(), so what an audit entry contains is decided
in exactly one place.
"""

from .context import get_current_request
from .models import AuditLog


def _client_ip(request):
    """
    Behind Nginx, REMOTE_ADDR is Nginx itself; the real client is the FIRST
    entry of X-Forwarded-For (later entries are proxies appending themselves).
    Trustworthy only because our Nginx sets/overwrites the header — a
    client-supplied value never survives. Direct connections (dev) fall back
    to REMOTE_ADDR.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log(*, action, actor=None, target=None, changes=None, request=None) -> AuditLog:
    """
    Append one audit entry. Keyword-only, like record().

    actor/request are usually omitted: the request comes from the middleware's
    ContextVar and the actor from request.user. Pass them explicitly only when
    the context can't know them (login: the user isn't authenticated yet;
    Celery: there is no request).
    """
    request = request or get_current_request()

    if actor is None and request is not None:
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            actor = user

    entry = AuditLog(
        actor=actor,
        actor_repr=str(actor) if actor else "",
        action=action,
        changes=changes or {},
    )
    if target is not None:
        entry.target = target
        # Truncate defensively: __str__ is developer-controlled free text.
        entry.target_repr = str(target)[:200]
    if request is not None:
        entry.ip_address = _client_ip(request)
        entry.user_agent = request.META.get("HTTP_USER_AGENT", "")[:300]
        entry.method = request.method
        entry.path = request.path[:200]
    entry.save()
    return entry
