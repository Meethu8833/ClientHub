"""
Global search API:

    /search/    GET  ?q=<term>[&types=clients,projects][&limit=5]

A plain APIView (dashboard's reasoning): no model, no pagination class, no
serializer — the payload is built dicts whose shape is pinned by tests and
documented in extend_schema.

Deliberately NOT cached: search keys have near-infinite cardinality (every
keystroke is a new key), so a cache would hold thousands of entries that are
each read ~once — all cost, no hit rate. The dashboard caches because many
users ask the SAME question; search users each ask a different one.

Validation is strict and cheap, in order:
  * q required, min 2 chars after strip — 1-char ILIKE matches half the
    database and a trigram index needs 3 chars to bite; short queries are
    pure load for garbage results.
  * limit clamped 1..20 — a client asking for 10_000 rows per type is a
    bug or an attack; the server, not the caller, owns its worst case.
  * types must be real type names — a typo ("cleints") 400s instead of
    silently returning nothing forever.
Types the ROLE cannot see are not an error: they are simply absent
(services.global_search drops them), so a staff request with
types=invoices returns {} rather than confirming invoices exist.
"""

from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import services


@extend_schema(
    summary="Global search",
    description=(
        "Search clients, contacts, projects, tasks, tickets, quotations "
        "(+invoices for manager/admin, +users for admin) in one call. "
        "Results are grouped by type, capped at `limit` per type, and "
        "scoped by the same visibility rules as each module's list "
        "endpoint. Prose fields use Postgres full-text search (stemming + "
        "relevance rank); identifier fields use substring match."
    ),
    parameters=[
        OpenApiParameter("q", str, required=True, description="Search term, min 2 chars"),
        OpenApiParameter(
            "types",
            str,
            description="Comma-separated subset of: " + ", ".join(sorted(services.ALL_TYPES)),
        ),
        OpenApiParameter("limit", int, description="Max results per type (1-20, default 5)"),
    ],
    responses={200: OpenApiResponse(description="Results grouped by entity type")},
)
class GlobalSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        if len(q) < services.MIN_QUERY_LENGTH:
            raise ValidationError(
                {"q": f"Provide at least {services.MIN_QUERY_LENGTH} characters."}
            )

        try:
            limit = int(request.query_params.get("limit", services.DEFAULT_LIMIT))
        except ValueError:
            raise ValidationError({"limit": "Must be an integer."}) from None
        limit = max(1, min(limit, services.MAX_LIMIT))

        types = None
        raw_types = request.query_params.get("types", "").strip()
        if raw_types:
            types = {t.strip() for t in raw_types.split(",") if t.strip()}
            unknown = types - services.ALL_TYPES
            if unknown:
                raise ValidationError({"types": f"Unknown type(s): {', '.join(sorted(unknown))}"})

        return Response(services.global_search(request.user, q, types, limit))
