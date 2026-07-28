"""
Global search (docs/search-module.md).

One query per entity type, each capped at `limit`, all read-only. Two match
strategies, chosen per field shape:

* SHORT IDENTIFIERS (names, emails, document numbers) — `icontains`, which
  compiles to `ILIKE '%term%'`. Substring semantics is what users expect
  here ("0042" must find INV-2026-0042), and the trigram GIN indexes added
  in each model's Meta keep it from degenerating into a full-table scan.
* LONG PROSE (descriptions, ticket bodies) — Postgres full-text search.
  `SearchVector` normalizes words to stems ("deployed"→"deploy") at match
  time and `SearchRank` orders by relevance. The vector expression below
  MUST stay byte-identical to the expression index in each model's Meta
  (same fields, same config), or Postgres silently falls back to computing
  the vector per-row and the index is dead weight.

Prose models get BOTH strategies OR-ed together: FTS alone cannot match a
partial word ("epor" is no stem), and substring alone knows nothing about
word forms. The OR lets Postgres bitmap-combine both GIN indexes.

Row visibility is the module rule everywhere else in ClientHub:
"whatever a role can LIST, it may SEARCH" — each _search_* copies the
queryset scoping of that module's list endpoint (§8). Types a role cannot
list are absent from the response entirely (dashboard's billing-blackout
pattern: an empty list would still leak that the type exists for others).
"""

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import Q

from apps.accounts.models import User
from apps.billing.models import Invoice
from apps.clients.models import Client, Contact
from apps.projects.models import Project, Task
from apps.quotations.models import Quotation
from apps.tickets.models import Ticket

MIN_QUERY_LENGTH = 2
DEFAULT_LIMIT = 5
MAX_LIMIT = 20

# The FTS config. One place, because index and query must agree on it.
FTS_CONFIG = "english"


def allowed_types(user) -> set[str]:
    """The entity types this role may search — mirror of §8's LIST column."""
    allowed = {"clients", "contacts", "projects", "tasks", "tickets", "quotations"}
    if user.role in (User.Role.ADMIN, User.Role.MANAGER):
        allowed.add("invoices")  # billing is a manager/admin area
    if user.role == User.Role.ADMIN:
        allowed.add("users")  # user management is admin-only
    return allowed


def _hit(obj, type_: str, title: str, subtitle: str) -> dict:
    """One uniform result row — the frontend renders every type the same way."""
    return {"type": type_, "id": obj.id, "title": title, "subtitle": subtitle}


def _page(qs, limit: int) -> tuple[list, bool]:
    """
    Fetch limit+1 rows: the extra row answers "is there more?" without a
    COUNT(*) — counting an ILIKE match costs as much as scanning it.
    """
    rows = list(qs[: limit + 1])
    return rows[:limit], len(rows) > limit


def _fts_filter(q: str, *fields: str) -> tuple[Q, SearchRank, SearchVector]:
    """
    Build the prose-model match: (stemmed word match OR substring on the
    first/short field), plus the rank annotation for relevance ordering.
    """
    vector = SearchVector(*fields, config=FTS_CONFIG)
    query = SearchQuery(q, config=FTS_CONFIG)
    match = Q(fts=query) | Q(**{f"{fields[0]}__icontains": q})
    return match, SearchRank(vector, query), vector


def _search_clients(user, q, limit):
    qs = (
        Client.objects.filter(is_active=True)  # same rule as ClientViewSet
        .filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(gst_number__icontains=q))
        .order_by("name")
    )
    items, more = _page(qs, limit)
    return [_hit(c, "client", c.name, f"{c.status} · {c.city}".rstrip(" ·")) for c in items], more


def _search_contacts(user, q, limit):
    qs = (
        Contact.objects.filter(client__is_active=True)
        .filter(Q(name__icontains=q) | Q(email__icontains=q))
        .select_related("client")  # subtitle reads client.name — avoid N+1
        .order_by("name")
    )
    items, more = _page(qs, limit)
    return [
        _hit(c, "contact", c.name, f"{c.position or 'Contact'} at {c.client.name}")
        for c in items
    ], more


def _search_projects(user, q, limit):
    match, rank, vector = _fts_filter(q, "name", "description")
    qs = Project.objects.filter(is_active=True)
    if user.role == User.Role.STAFF:
        qs = qs.filter(memberships__user=user)  # §8: staff see member projects
    qs = (
        qs.annotate(fts=vector, rank=rank)
        .filter(match)
        .select_related("client")
        # DISTINCT: the memberships JOIN above can duplicate a project row.
        .distinct()
        .order_by("-rank", "-created_at")
    )
    items, more = _page(qs, limit)
    return [_hit(p, "project", p.name, f"{p.client.name} · {p.status}") for p in items], more


def _search_tasks(user, q, limit):
    match, rank, vector = _fts_filter(q, "title", "description")
    qs = Task.objects.filter(project__is_active=True)
    if user.role == User.Role.STAFF:
        qs = qs.filter(project__memberships__user=user)
    qs = (
        qs.annotate(fts=vector, rank=rank)
        .filter(match)
        .select_related("project")
        .distinct()
        .order_by("-rank", "-created_at")
    )
    items, more = _page(qs, limit)
    return [_hit(t, "task", t.title, f"{t.project.name} · {t.status}") for t in items], more


def _search_tickets(user, q, limit):
    # Shared queue: every role sees every ticket (tickets module rule).
    match, rank, vector = _fts_filter(q, "subject", "description")
    qs = (
        Ticket.objects.annotate(fts=vector, rank=rank)
        .filter(match)
        .select_related("client")
        .order_by("-rank", "-created_at")
    )
    items, more = _page(qs, limit)
    return [_hit(t, "ticket", t.subject, f"{t.client.name} · {t.status}") for t in items], more


def _search_quotations(user, q, limit):
    qs = Quotation.objects.all()
    if user.role == User.Role.STAFF:
        qs = qs.filter(created_by=user)  # §8: staff see own quotations
    qs = (
        qs.filter(Q(title__icontains=q) | Q(quote_number__icontains=q))
        .select_related("client")
        .order_by("-created_at")
    )
    items, more = _page(qs, limit)
    return [
        _hit(x, "quotation", x.title, f"{x.quote_number} · {x.client.name} · {x.status}")
        for x in items
    ], more


def _search_invoices(user, q, limit):
    qs = (
        Invoice.objects.filter(
            Q(invoice_number__icontains=q) | Q(client__name__icontains=q)
        )
        .select_related("client")
        .order_by("-created_at")
    )
    items, more = _page(qs, limit)
    return [
        _hit(i, "invoice", i.invoice_number or f"Draft #{i.id}", f"{i.client.name} · {i.status}")
        for i in items
    ], more


def _search_users(user, q, limit):
    qs = (
        User.objects.filter(deleted_at__isnull=True)  # same rule as /users/
        .filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(email__icontains=q))
        .order_by("email")
    )
    items, more = _page(qs, limit)
    return [
        _hit(u, "user", u.get_full_name() or u.email, f"{u.email} · {u.role}") for u in items
    ], more


_SEARCHERS = {
    "clients": _search_clients,
    "contacts": _search_contacts,
    "projects": _search_projects,
    "tasks": _search_tasks,
    "tickets": _search_tickets,
    "quotations": _search_quotations,
    "invoices": _search_invoices,
    "users": _search_users,
}

# The view validates `types` against this (400 on typos, not silence).
ALL_TYPES = set(_SEARCHERS)


def global_search(user, q: str, types: set[str] | None, limit: int) -> dict:
    """
    Run every (allowed ∩ requested) searcher and group the results by type.

    Types outside the caller's §8 visibility are dropped WITHOUT error:
    requested-but-forbidden must look exactly like "no such data" (the
    dashboard's billing-blackout rule).
    """
    wanted = allowed_types(user)
    if types:
        wanted &= types

    results = {}
    for type_ in sorted(wanted):
        items, has_more = _SEARCHERS[type_](user, q, limit)
        results[type_] = {"items": items, "has_more": has_more}
    return {"query": q, "limit": limit, "results": results}
