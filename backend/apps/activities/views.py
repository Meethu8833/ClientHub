"""
Notes API (ARCHITECTURE.md §6):

    POST   /notes/                                   create (any role)
    GET    /notes/?content_type=client&object_id=7   list for one object
    GET    /notes/{id}/
    PATCH  /notes/{id}/    author or manager/admin
    DELETE /notes/{id}/    author or manager/admin (matrix: staff own only)
"""

from django.contrib.contenttypes.models import ContentType
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core import attachments
from apps.core.permissions import IsOwnerOrManager

from .models import Activity, Note
from .serializers import (
    ActivitySerializer,
    NoteCreateSerializer,
    NoteSerializer,
    NoteUpdateSerializer,
)


class NoteViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    owner_field = "author"  # read by IsOwnerOrManager
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        perms = super().get_permissions()
        if self.action in ("partial_update", "destroy"):
            perms.append(IsOwnerOrManager())
        return perms

    def get_queryset(self):
        qs = Note.objects.select_related("author", "content_type").order_by("-created_at")
        if self.action == "list":
            slug = self.request.query_params["content_type"]  # validated in list()
            model = attachments.resolve_attachable(slug)
            qs = qs.filter(
                content_type=ContentType.objects.get_for_model(model),
                object_id=int(self.request.query_params["object_id"]),
            )
        return qs

    def get_serializer_class(self):
        return {
            "create": NoteCreateSerializer,
            "partial_update": NoteUpdateSerializer,
        }.get(self.action, NoteSerializer)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        note = serializer.save()
        data = NoteSerializer(note, context=self.get_serializer_context()).data
        return Response(data, status=status.HTTP_201_CREATED)

    def list(self, request, *args, **kwargs):
        slug = request.query_params.get("content_type")
        object_id = request.query_params.get("object_id", "")
        if slug not in attachments.attachable_slugs() or not str(object_id).isdigit():
            raise ValidationError(
                {"detail": "Provide ?content_type=<client>&object_id=<id> to list notes."}
            )
        if attachments.get_visible_target(slug, int(object_id), user=request.user) is None:
            raise ValidationError({"object_id": f"No {slug} with id {object_id}."})
        return super().list(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        super().update(request, *args, **kwargs)
        return Response(
            NoteSerializer(self.get_object(), context=self.get_serializer_context()).data
        )


class ActivityViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """
    GET /activities/?content_type=project&object_id=7 — the history tab.
    List-only: activities are never created, edited or deleted over the API.
    The parent params are mandatory (same rule as notes/documents): a global
    activity dump is not a screen and would leak across scoping rules.
    """

    serializer_class = ActivitySerializer

    def get_queryset(self):
        slug = self.request.query_params["content_type"]  # validated in list()
        model = attachments.resolve_attachable(slug)
        return (
            Activity.objects.select_related("actor", "content_type")
            .filter(
                content_type=ContentType.objects.get_for_model(model),
                object_id=int(self.request.query_params["object_id"]),
            )
            .order_by("-created_at")
        )

    def list(self, request, *args, **kwargs):
        slug = request.query_params.get("content_type")
        object_id = request.query_params.get("object_id", "")
        if slug not in attachments.attachable_slugs() or not str(object_id).isdigit():
            raise ValidationError(
                {"detail": "Provide ?content_type=<slug>&object_id=<id> to list activities."}
            )
        if attachments.get_visible_target(slug, int(object_id), user=request.user) is None:
            raise ValidationError({"object_id": f"No {slug} with id {object_id}."})
        return super().list(request, *args, **kwargs)
