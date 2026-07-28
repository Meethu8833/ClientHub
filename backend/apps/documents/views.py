"""
Documents API (ARCHITECTURE.md §6, §9):

    POST   /documents/                multipart upload (any authenticated role)
    GET    /documents/?content_type=client&object_id=7   list for one object
    GET    /documents/{id}/           metadata (current version)
    GET    /documents/{id}/versions/  full version history
    POST   /documents/{id}/versions/  upload a NEW version (owner or manager+)
    GET    /documents/{id}/download/  the bytes, permission-checked
                                      (?version=N for an older version)
    DELETE /documents/{id}/           admin/manager any; staff own only

Deliberately NO update/PATCH: a version is immutable evidence. "Replacing"
a file means appending a new version — the old bytes stay downloadable, so
the audit trail can never be quietly rewritten.
"""

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.files.storage import FileSystemStorage
from django.db.models import Count
from django.http import FileResponse, HttpResponse, HttpResponseRedirect
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.core import attachments
from apps.core.permissions import IsOwnerOrManager

from .models import Document
from .serializers import (
    DocumentSerializer,
    DocumentUploadSerializer,
    DocumentVersionSerializer,
    DocumentVersionUploadSerializer,
)


class DocumentViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    owner_field = "uploaded_by"  # read by IsOwnerOrManager (destroy + new version)

    def get_permissions(self):
        # Everyone authenticated may upload/view (matrix: "on objects they can
        # see"). Destroying — or re-versioning — someone else's file needs
        # manager/admin: both actions change what the document "is".
        perms = super().get_permissions()
        if self.action == "destroy" or (
            self.action == "versions" and self.request.method == "POST"
        ):
            perms.append(IsOwnerOrManager())
        return perms

    def get_queryset(self):
        qs = (
            Document.objects.select_related("uploaded_by", "content_type", "current_version")
            .annotate(versions_count=Count("versions"))
            .order_by("-created_at")
        )
        if self.action == "list":
            # list() has already validated these params and the target's
            # existence before the queryset is ever evaluated.
            slug = self.request.query_params["content_type"]
            model = attachments.resolve_attachable(slug)
            qs = qs.filter(
                content_type=ContentType.objects.get_for_model(model),
                object_id=int(self.request.query_params["object_id"]),
            )
        return qs

    def get_serializer_class(self):
        return DocumentUploadSerializer if self.action == "create" else DocumentSerializer

    def create(self, request, *args, **kwargs):
        # Validate with the upload serializer, respond with the read shape.
        upload = self.get_serializer(data=request.data)
        upload.is_valid(raise_exception=True)
        document = upload.save()
        data = DocumentSerializer(document, context=self.get_serializer_context()).data
        return Response(data, status=status.HTTP_201_CREATED)

    def list(self, request, *args, **kwargs):
        # A global "every file in the system" dump is never a real screen and
        # would leak across future scoping rules — the parent is mandatory.
        slug = request.query_params.get("content_type")
        object_id = request.query_params.get("object_id", "")
        if slug not in attachments.attachable_slugs() or not str(object_id).isdigit():
            raise ValidationError(
                {"detail": "Provide ?content_type=<client>&object_id=<id> to list documents."}
            )
        if attachments.get_visible_target(slug, int(object_id), user=request.user) is None:
            raise ValidationError({"object_id": f"No {slug} with id {object_id}."})
        return super().list(request, *args, **kwargs)

    @action(detail=True, methods=["get", "post"])
    def versions(self, request, pk=None):
        """GET: full history, newest first. POST: append a new version."""
        document = self.get_object()

        if request.method == "GET":
            history = document.versions.select_related("uploaded_by")
            data = DocumentVersionSerializer(
                history, many=True, context=self.get_serializer_context()
            ).data
            return Response(data)

        upload = DocumentVersionUploadSerializer(
            data=request.data,
            context={**self.get_serializer_context(), "document": document},
        )
        upload.is_valid(raise_exception=True)
        version = upload.save()
        data = DocumentVersionSerializer(version, context=self.get_serializer_context()).data
        return Response(data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """
        Private media (§9): the file NEVER has a public /media/ URL. Django
        authenticates + authorizes, then hands off the bytes three ways:

        - remote storage (S3): 302 to a short-lived PRESIGNED url — the bucket
          is private; the signature in the query string is the access grant.
        - prod local + Nginx: X-Accel-Redirect — auth in Python, bytes in C.
        - dev: Django streams the file itself.

        ?version=N downloads an older version; default is the current one.
        """
        document = self.get_object()
        version = self._requested_version(request, document)

        storage = version.file.storage
        if not isinstance(storage, FileSystemStorage):
            disposition = f'attachment; filename="{document.original_name}"'
            try:
                # S3Storage.url() accepts per-request parameters — this makes
                # the browser save the file under its real name, not the UUID.
                url = storage.url(
                    version.file.name,
                    parameters={"ResponseContentDisposition": disposition},
                )
            except TypeError:  # a remote backend without parameters support
                url = version.file.url
            return HttpResponseRedirect(url)

        accel_prefix = getattr(settings, "DOCUMENT_X_ACCEL_PREFIX", "")
        if accel_prefix:
            response = HttpResponse()
            response["Content-Type"] = version.mime_type
            response["Content-Disposition"] = f'attachment; filename="{document.original_name}"'
            # e.g. /internal-media/documents/2026/07/ab12….pdf — an `internal;`
            # location in nginx.conf, unreachable directly from the internet.
            response["X-Accel-Redirect"] = f"{accel_prefix}{version.file.name}"
            return response

        # Dev fallback: Django streams the bytes itself.
        return FileResponse(
            version.file.open("rb"),
            as_attachment=True,
            filename=document.original_name,
            content_type=version.mime_type,
        )

    def _requested_version(self, request, document):
        """Resolve ?version=N (or the current version). 400 on garbage,
        404 on a number that never existed — different failures, different codes."""
        param = request.query_params.get("version")
        if param is None:
            if document.current_version is None:  # defensive; services prevent this
                raise NotFound("Document has no stored file.")
            return document.current_version
        if not param.isdigit():
            raise ValidationError({"version": "Must be a positive integer."})
        version = document.versions.filter(version_number=int(param)).first()
        if version is None:
            raise NotFound(f"No version {param} for this document.")
        return version
