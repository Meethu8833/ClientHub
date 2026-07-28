"""
Registry of models that documents and notes may attach to (ARCHITECTURE.md §4).

Both `documents.Document` and `activities.Note` point at their parent with a
GenericForeignKey (content_type + object_id), which technically could reference
ANY table. That is too permissive for an API: a caller could attach a file to
a User row, a token row, anything. This registry is the single whitelist both
apps consult, keyed by a short public slug the frontend sends
("client" today; "project", "task", "deal" as those apps land).

Living in core because it is shared plumbing — documents and activities must
not import from each other (same rule as the frontend's "features never import
features").
"""

from django.apps import apps

# public slug -> "app_label.ModelName"
ATTACHABLE_MODELS = {
    "client": "clients.Client",
    "project": "projects.Project",
    "task": "projects.Task",
    "ticket": "tickets.Ticket",
    "quotation": "quotations.Quotation",
    "invoice": "billing.Invoice",
    "meeting": "meetings.Meeting",
    # "deal": "sales.Deal",            # Phase 3
}


def attachable_slugs():
    """Choices for serializers: the slugs a caller may pass as `content_type`."""
    return list(ATTACHABLE_MODELS)


def resolve_attachable(slug):
    """Slug -> model class. apps.get_model avoids circular imports at module load."""
    return apps.get_model(ATTACHABLE_MODELS[slug])


def slug_for_model(model_cls):
    """Model class -> public slug (for read serializers). None if not attachable."""
    label = f"{model_cls._meta.app_label}.{model_cls.__name__}"
    for slug, target in ATTACHABLE_MODELS.items():
        if target == label:
            return slug
    return None


def get_visible_target(slug, object_id, user=None):
    """
    Fetch the parent object a caller wants to attach to, or None if it does
    not exist / is soft-deleted / is OUT OF THE CALLER'S SCOPE. All three must
    behave identically ("no such object"), or the response would leak which
    projects exist to people not on them.

    Scope rule (matrix §8): STAFF see only projects they are members of;
    clients are visible to every authenticated role. `user=None` (internal
    callers) skips scoping.
    """
    model = resolve_attachable(slug)
    qs = model.objects.all()
    if hasattr(model, "is_active"):  # soft-deleted parents are invisible
        qs = qs.filter(is_active=True)
    if slug == "task":  # a task inherits visibility from its project
        qs = qs.filter(project__is_active=True)
    if slug in ("project", "task") and user is not None:
        from apps.accounts.models import User  # local: keep core import-light

        if user.role == User.Role.STAFF:
            member_path = "memberships__user" if slug == "project" else "project__memberships__user"
            qs = qs.filter(**{member_path: user})
    if slug == "quotation" and user is not None:
        from apps.accounts.models import User

        # Same scope as the quotations API: staff attach only to their own.
        if user.role == User.Role.STAFF:
            qs = qs.filter(created_by=user)
    if slug == "invoice" and user is not None:
        from apps.accounts.models import User

        # Billing row of the matrix (§8): STAFF have no access at all.
        if user.role == User.Role.STAFF:
            return None
    if slug == "meeting" and user is not None:
        from django.db.models import Q

        from apps.accounts.models import User

        # Same scope as the meetings API: staff attach only to meetings they
        # organize or attend.
        if user.role == User.Role.STAFF:
            qs = qs.filter(Q(organizer=user) | Q(attendees__user=user)).distinct()
    return qs.filter(pk=object_id).first()
