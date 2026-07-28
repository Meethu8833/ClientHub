"""
Request context for audit logging.

Problem: signal handlers (signals.py) fire deep inside model.save() and know
nothing about the HTTP request — but an audit row needs WHO (user) and WHERE
FROM (IP). Passing the request down through every save() call would infect
every service function's signature.

Solution: the middleware parks the current request in a ContextVar, and
services.log() picks it up from here. A ContextVar is like a global variable
that is isolated per thread AND per async task, so two requests being handled
at the same time never see each other's data (a plain module-level global
would leak one user's identity into another user's audit row).

Outside a request (Celery tasks, management commands, the shell) there is no
request — get_current_request() returns None and audit rows simply record
actor=None, which is the truth: the system itself acted.
"""

from contextvars import ContextVar

_current_request: ContextVar = ContextVar("audit_current_request", default=None)


def set_current_request(request):
    """Store the request; returns a token used to undo exactly this set()."""
    return _current_request.set(request)


def reset_current_request(token):
    """Restore the previous value so nothing leaks into the next request."""
    _current_request.reset(token)


def get_current_request():
    return _current_request.get()
