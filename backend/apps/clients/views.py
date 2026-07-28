"""
Client & Contact API (ARCHITECTURE.md §6, §8 — Phase 2).

Permission matrix applied here: ADMIN/MANAGER full CRUD, STAFF read-only —
that is exactly core.permissions.ReadOnlyForStaff. No queryset scoping needed
(unlike projects later): every role may see every client.

Nesting rule (§6): one level, read/create only.
    /clients/{id}/contacts/  GET list + POST create  (the nested slice)
    /contacts/{id}/          GET/PATCH/DELETE        (flat for the rest)
"""

from django.db.models import Count
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.response import Response

from apps.core.permissions import ReadOnlyForStaff

from . import services
from .filters import ClientFilter
from .models import Client, Contact
from .serializers import (
    ClientDetailSerializer,
    ClientListSerializer,
    ClientWriteSerializer,
    ContactSerializer,
    ContactWriteSerializer,
)


class ClientViewSet(viewsets.ModelViewSet):
    """
    GET    /clients/                 list (?search= &status= &ordering= …)
    POST   /clients/                 create                (manager/admin)
    GET    /clients/{id}/            detail (+contacts)
    PATCH  /clients/{id}/            update                (manager/admin)
    DELETE /clients/{id}/            SOFT delete           (manager/admin)
    GET    /clients/{id}/contacts/   nested contact list
    POST   /clients/{id}/contacts/   nested contact create (manager/admin)
    """

    permission_classes = [ReadOnlyForStaff]
    filterset_class = ClientFilter
    search_fields = ["name", "email", "phone", "gst_number", "city", "industry"]
    ordering_fields = ["name", "status", "created_at", "updated_at"]  # ?ordering= whitelist
    ordering = ["-created_at"]  # deterministic pages

    def get_queryset(self):
        # Soft-deleted clients are invisible everywhere: list, detail, update,
        # delete and the nested contacts action all flow through here, so a
        # dead id consistently 404s (no existence leak).
        qs = (
            Client.objects.filter(is_active=True)
            .select_related("account_manager")  # JOIN, not one query per row
            .annotate(contact_count=Count("contacts"))  # COUNT in SQL, no N+1
        )
        if self.action == "retrieve":
            qs = qs.prefetch_related("contacts")  # detail embeds them
        return qs

    def get_serializer_class(self):
        return {
            "list": ClientListSerializer,
            "create": ClientWriteSerializer,
            "partial_update": ClientWriteSerializer,
            "contacts": ContactWriteSerializer,  # POST body validation
        }.get(self.action, ClientDetailSerializer)

    def _detail_response(self, client, status_code=status.HTTP_200_OK):
        # Writes validate with the slim serializer but ANSWER with the full
        # detail shape, so the frontend can refresh its cache from the response.
        client = self.get_queryset().prefetch_related("contacts").get(pk=client.pk)
        data = ClientDetailSerializer(client, context=self.get_serializer_context()).data
        return Response(data, status=status_code)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        client = serializer.save()
        return self._detail_response(client, status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        # PATCH only (same house rule as /users/): PUT means "replace the
        # whole record", which invites accidental blanking of fields the
        # caller didn't send.
        if not kwargs.get("partial"):
            raise MethodNotAllowed("PUT")
        super().update(request, *args, **kwargs)
        return self._detail_response(self.get_object())

    def destroy(self, request, *args, **kwargs):
        services.soft_delete_client(self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"])
    def check(self, request):
        """
        GET /clients/check/?name=Acme&gst_number=29ABCDE1234F1Z5&exclude=7

        Instant duplicate pre-check for the create/edit form: says whether a
        name or GSTIN is already taken while the user is still typing, instead
        of after submit. Advisory only — the serializer and DB constraints
        remain the enforcement on write.

        Deliberately queries the FULL table, not the is_active slice: the
        unique constraints cover soft-deleted rows too, so a check scoped to
        visible clients would answer "available" for a value the INSERT would
        still reject.
        """
        params = request.query_params
        qs = Client.objects.all()
        exclude = params.get("exclude", "")
        if exclude.isdigit():  # edit mode: a record never conflicts with itself
            qs = qs.exclude(pk=exclude)

        data = {}
        name = params.get("name", "").strip()
        if name:
            # iexact on purpose, stricter than the column's case-sensitive
            # unique: "acme corp" next to "Acme Corp" is a data-entry
            # duplicate in a CRM, and this is the moment to say so.
            data["name_taken"] = qs.filter(name__iexact=name).exists()
        gstin = params.get("gst_number", "").strip().upper()
        if gstin:
            data["gst_number_taken"] = qs.filter(gst_number=gstin).exists()
        return Response(data)

    @action(detail=True, methods=["get", "post"])
    def contacts(self, request, pk=None):
        client = self.get_object()  # 404s first if the client is soft-deleted

        if request.method == "GET":
            qs = client.contacts.all()
            page = self.paginate_queryset(qs)
            data = ContactSerializer(page, many=True).data
            return self.get_paginated_response(data)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        contact = serializer.save(client=client)  # client comes from the URL, not the body
        return Response(ContactSerializer(contact).data, status=status.HTTP_201_CREATED)


class ContactViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Flat writes (§6): GET/PATCH/DELETE /contacts/{id}/.
    No list/create here — listing without a client is meaningless, creating
    happens nested so the parent is explicit.
    """

    permission_classes = [ReadOnlyForStaff]
    http_method_names = ["get", "patch", "delete", "head", "options"]  # bans PUT

    def get_queryset(self):
        # Contacts of soft-deleted clients disappear with their company.
        return Contact.objects.filter(client__is_active=True).select_related("client")

    def get_serializer_class(self):
        return ContactWriteSerializer if self.action == "partial_update" else ContactSerializer

    def update(self, request, *args, **kwargs):
        super().update(request, *args, **kwargs)
        return Response(ContactSerializer(self.get_object()).data)
