"""
Middleware that makes the current request visible to the audit logger.

We store the REQUEST OBJECT, not request.user: this middleware runs before
DRF's JWT authentication (which happens inside the view layer), so at this
point request.user is still AnonymousUser for API calls. By the time a signal
handler asks for the user, DRF has authenticated and request.user is real —
reading it lazily through the stored request gets the right answer.

The finally block is not optional: gunicorn reuses worker threads, so a
context left behind by request A would still be set when request B arrives
on the same thread.
"""

from .context import reset_current_request, set_current_request


class AuditContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = set_current_request(request)
        try:
            return self.get_response(request)
        finally:
            reset_current_request(token)
