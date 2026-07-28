"""
Quotation API (docs/quotations-module.md):

    /quotations/                        list/create/retrieve/patch;
                                        DELETE only while DRAFT
    /quotations/{id}/items/             GET lines, POST add line (draft only)
    /quotation-items/{id}/              PATCH/DELETE one line (flat, draft only)
    /quotations/{id}/submit/            POST  draft → pending_approval
    /quotations/{id}/approve/           POST  {note?}     manager/admin, not author
    /quotations/{id}/request-changes/   POST  {note}      manager/admin
    /quotations/{id}/send/              POST  approved → sent
    /quotations/{id}/accept/            POST  sent → accepted (expiry-guarded)
    /quotations/{id}/decline/           POST  {reason?}  sent → declined
    /quotations/{id}/cancel/            POST  withdraw before a client decision
    /quotations/{id}/revise/            POST  cut version N+1 → 201 new draft

Visibility follows the Leads/Deals row of the §8 matrix (quotes are sales
records with money on them): STAFF see and manage ONLY quotations they
created; managers/admins see all. Scoping is queryset filtering, so
out-of-scope quotes 404 rather than 403 (don't leak existence).
"""

from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.accounts.models import User
from apps.core.permissions import IsManagerOrAdmin, IsOwnerOrManager

from . import services
from .filters import QuotationFilter
from .models import Quotation, QuotationItem
from .serializers import (
    ApproveSerializer,
    DeclineSerializer,
    QuotationDetailSerializer,
    QuotationItemSerializer,
    QuotationItemWriteSerializer,
    QuotationListSerializer,
    QuotationWriteSerializer,
    RequestChangesSerializer,
)


class QuotationViewSet(viewsets.ModelViewSet):
    owner_field = "created_by"  # read by IsOwnerOrManager: "owning" a quote = having created it
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]  # no PUT (§6)
    filterset_class = QuotationFilter
    search_fields = ["quote_number", "title", "client__name"]
    ordering_fields = ["created_at", "grand_total", "valid_until"]
    ordering = ["-created_at"]

    def get_queryset(self):
        # §6 N+1 discipline: every FK the serializers touch is joined; items
        # and the revision chain are prefetched for the detail shape.
        qs = Quotation.objects.select_related(
            "client", "contact", "created_by", "approved_by"
        ).prefetch_related("items", "revisions")
        # §8 layer 2: staff see only their own sales records.
        if self.request.user.role == User.Role.STAFF:
            qs = qs.filter(created_by=self.request.user)
        return qs

    def get_serializer_class(self):
        if self.action == "list":
            return QuotationListSerializer
        if self.action in ("create", "partial_update", "update"):
            return QuotationWriteSerializer
        return QuotationDetailSerializer

    def get_permissions(self):
        perms = super().get_permissions()
        # The approval gate is a MANAGEMENT act (§8: staff never sign off).
        if self.action in ("approve", "request_changes"):
            perms.append(IsManagerOrAdmin())
        # Everything else that mutates: managers always, staff on own quotes.
        elif self.action not in ("list", "retrieve", "create"):
            perms.append(IsOwnerOrManager())
        return perms

    def _detail(self, quotation, http_status=status.HTTP_200_OK):
        """Every mutation answers with the same full-detail shape."""
        serializer = QuotationDetailSerializer(quotation, context=self.get_serializer_context())
        return Response(serializer.data, status=http_status)

    # -- create / update / delete → services ---------------------------------

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quotation = services.create_quotation(
            quotation=Quotation(**serializer.validated_data), actor=request.user
        )
        return self._detail(quotation, http_status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(instance, field, value)
        return self._detail(services.update_quotation(quotation=instance, actor=request.user))

    def perform_destroy(self, instance):
        # Drafts that never reached anyone are scrap paper — deletable.
        # Anything submitted or beyond is business history: cancel or revise.
        if instance.status != Quotation.Status.DRAFT:
            raise ValidationError(
                {"detail": "Only drafts can be deleted — cancel the quotation instead."}
            )
        instance.delete()

    # -- line items -----------------------------------------------------------

    @action(detail=True, methods=["get", "post"])
    def items(self, request, pk=None):
        quotation = self.get_object()
        if request.method == "GET":
            return Response(QuotationItemSerializer(quotation.items.all(), many=True).data)

        serializer = QuotationItemWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = services.add_item(
            quotation=quotation,
            item=QuotationItem(**serializer.validated_data),
            actor=request.user,
        )
        return Response(QuotationItemSerializer(item).data, status=status.HTTP_201_CREATED)

    # -- lifecycle verbs ------------------------------------------------------

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        return self._detail(
            services.submit_quotation(quotation=self.get_object(), actor=request.user)
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        serializer = ApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._detail(
            services.approve_quotation(
                quotation=self.get_object(),
                actor=request.user,
                note=serializer.validated_data["note"],
            )
        )

    @action(detail=True, methods=["post"], url_path="request-changes")
    def request_changes(self, request, pk=None):
        serializer = RequestChangesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._detail(
            services.request_changes(
                quotation=self.get_object(),
                actor=request.user,
                note=serializer.validated_data["note"],
            )
        )

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        return self._detail(
            services.send_quotation(quotation=self.get_object(), actor=request.user)
        )

    @action(detail=True, methods=["post"])
    def accept(self, request, pk=None):
        return self._detail(
            services.accept_quotation(quotation=self.get_object(), actor=request.user)
        )

    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        serializer = DeclineSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._detail(
            services.decline_quotation(
                quotation=self.get_object(),
                actor=request.user,
                reason=serializer.validated_data["reason"],
            )
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._detail(
            services.cancel_quotation(quotation=self.get_object(), actor=request.user)
        )

    @action(detail=True, methods=["post"])
    def revise(self, request, pk=None):
        """201: revise CREATES a resource (the next version's draft)."""
        new = services.revise_quotation(quotation=self.get_object(), actor=request.user)
        return self._detail(new, http_status=status.HTTP_201_CREATED)


class QuotationItemViewSet(
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """
    Flat writes for one line (§6: nested is read/create only; update/delete
    hit the flat resource). Draft-only, enforced in services.
    """

    serializer_class = QuotationItemWriteSerializer
    http_method_names = ["patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = QuotationItem.objects.select_related("quotation__created_by")
        # Same scope as the parent: staff touch only lines of their own quotes.
        if self.request.user.role == User.Role.STAFF:
            qs = qs.filter(quotation__created_by=self.request.user)
        return qs

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(instance, field, value)
        item = services.update_item(item=instance, actor=request.user)
        return Response(QuotationItemSerializer(item).data)

    def perform_destroy(self, instance):
        services.delete_item(item=instance, actor=self.request.user)
