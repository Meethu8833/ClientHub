"""
Support Ticket API (docs/tickets-module.md):

    /ticket-categories/            CRUD-minus-delete  (write: manager/admin)
    /sla-policies/                 list/retrieve all, PATCH admin only
    /tickets/                      list/create/retrieve/patch — NO delete, ever
    /tickets/{id}/replies/         GET thread, POST reply
    /tickets/{id}/claim/           POST  take an unassigned ticket yourself
    /tickets/{id}/assign/          POST  manager/admin hand-over {assignee_id}
    /tickets/{id}/escalate/        POST  {reason?}
    /tickets/{id}/resolve/         POST  {summary}   assignee or manager/admin
    /tickets/{id}/close/           POST              assignee or manager/admin
    /tickets/{id}/reopen/          POST

Visibility: tickets are a SHARED queue — every authenticated role sees every
ticket (unlike leads/deals, support work is handed around constantly, and a
ticket only its creator could see would be unanswerable on their day off).
What STAFF may *change* is restricted instead: only tickets assigned to them.
"""

from django.db.models import Count
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.permissions import IsAdmin, IsOwnerOrManager, ReadOnlyForStaff

from . import services
from .filters import TicketFilter
from .models import SlaPolicy, Ticket, TicketCategory
from .serializers import (
    AssignSerializer,
    EscalateSerializer,
    ResolveSerializer,
    SlaPolicySerializer,
    TicketCategorySerializer,
    TicketDetailSerializer,
    TicketListSerializer,
    TicketReplyCreateSerializer,
    TicketReplySerializer,
    TicketWriteSerializer,
)


class TicketCategoryViewSet(viewsets.ModelViewSet):
    """
    No DELETE in http_method_names: categories are PROTECTed by tickets, so a
    delete would 500 the moment a category has history. Retirement is
    PATCH {"is_active": false} — old tickets keep it, new tickets can't pick it.
    """

    queryset = TicketCategory.objects.all()
    serializer_class = TicketCategorySerializer
    permission_classes = [ReadOnlyForStaff]
    http_method_names = ["get", "post", "patch", "head", "options"]


class SlaPolicyViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    Everyone may READ the promises (the UI shows deadlines); only admins tune
    them (§8: global settings = admin). No create/delete: the four rows (one
    per priority) are seeded by migration and are the complete universe.
    """

    queryset = SlaPolicy.objects.order_by("pk")
    serializer_class = SlaPolicySerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_permissions(self):
        perms = super().get_permissions()
        if self.action == "partial_update":
            perms.append(IsAdmin())
        return perms


class TicketViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    owner_field = "assignee"  # read by IsOwnerOrManager: "owning" a ticket = being its assignee
    http_method_names = ["get", "post", "patch", "head", "options"]  # no delete — ever
    filterset_class = TicketFilter
    search_fields = ["subject", "description", "client__name"]
    ordering_fields = ["created_at", "updated_at", "resolution_due_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        # §6 N+1 discipline: every FK the serializers touch is joined here;
        # reply_count comes as one aggregate instead of a query per row.
        return Ticket.objects.select_related(
            "client", "contact", "category", "assignee", "created_by", "escalated_by"
        ).annotate(reply_count=Count("replies"))

    def get_serializer_class(self):
        if self.action == "list":
            return TicketListSerializer
        if self.action in ("create", "partial_update"):
            return TicketWriteSerializer
        return TicketDetailSerializer

    def get_permissions(self):
        perms = super().get_permissions()
        # Editing fields / delivering outcomes: managers always; staff only on
        # tickets assigned to them (claim first, then work).
        if self.action in ("partial_update", "resolve", "close"):
            perms.append(IsOwnerOrManager())
        return perms

    def _detail(self, ticket, http_status=status.HTTP_200_OK):
        """Every mutation answers with the same full-detail shape."""
        serializer = TicketDetailSerializer(ticket, context=self.get_serializer_context())
        return Response(serializer.data, status=http_status)

    # -- create / update → services (SLA stamping, history rows) -------------

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = services.create_ticket(
            ticket=Ticket(**serializer.validated_data), actor=request.user
        )
        return self._detail(ticket, http_status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(instance, field, value)
        ticket = services.update_ticket(ticket=instance, actor=request.user)
        return self._detail(ticket)

    # -- the conversation thread ---------------------------------------------

    @action(detail=True, methods=["get", "post"])
    def replies(self, request, pk=None):
        ticket = self.get_object()
        if request.method == "GET":
            qs = ticket.replies.select_related("author")
            page = self.paginate_queryset(qs)
            return self.get_paginated_response(TicketReplySerializer(page, many=True).data)

        serializer = TicketReplyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reply = services.add_reply(ticket=ticket, author=request.user, **serializer.validated_data)
        return Response(TicketReplySerializer(reply).data, status=status.HTTP_201_CREATED)

    # -- lifecycle verbs -------------------------------------------------------

    @action(detail=True, methods=["post"])
    def claim(self, request, pk=None):
        """Take an unassigned ticket yourself — the staff-friendly path."""
        ticket = self.get_object()
        if ticket.assignee_id is not None and ticket.assignee_id != request.user.pk:
            raise ValidationError({"detail": "Already assigned — ask a manager to reassign it."})
        return self._detail(
            services.assign_ticket(ticket=ticket, assignee=request.user, actor=request.user)
        )

    @action(detail=True, methods=["post"], permission_classes=[ReadOnlyForStaff])
    def assign(self, request, pk=None):
        """Manager hand-over (ReadOnlyForStaff: POST is a write → staff 403)."""
        ticket = self.get_object()
        serializer = AssignSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._detail(
            services.assign_ticket(
                ticket=ticket,
                assignee=serializer.validated_data["assignee_id"],
                actor=request.user,
            )
        )

    @action(detail=True, methods=["post"])
    def escalate(self, request, pk=None):
        """Any role may raise the flag — that is the whole point of escalation."""
        ticket = self.get_object()
        serializer = EscalateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._detail(
            services.escalate_ticket(
                ticket=ticket, actor=request.user, reason=serializer.validated_data["reason"]
            )
        )

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        ticket = self.get_object()
        serializer = ResolveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._detail(
            services.resolve_ticket(
                ticket=ticket, actor=request.user, summary=serializer.validated_data["summary"]
            )
        )

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        ticket = self.get_object()
        return self._detail(services.close_ticket(ticket=ticket, actor=request.user))

    @action(detail=True, methods=["post"])
    def reopen(self, request, pk=None):
        ticket = self.get_object()
        return self._detail(services.reopen_ticket(ticket=ticket, actor=request.user))
