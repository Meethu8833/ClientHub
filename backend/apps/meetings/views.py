"""
Meeting Scheduler API (docs/meetings-module.md):

    /meetings/                       list/create/retrieve/patch — NO delete
    /meetings/{id}/reschedule/       POST {scheduled_start, scheduled_end}
    /meetings/{id}/cancel/           POST {reason}
    /meetings/{id}/complete/         POST
    /meetings/{id}/no-show/          POST
    /meetings/{id}/respond/          POST {response}   RSVP, any attendee
    /meetings/{id}/attendees/        GET list, POST add one
    /meeting-attendees/{id}/         DELETE (flat, §6 convention)
    /meetings/{id}/minutes/          GET / PUT (create-or-update, OneToOne)
    /meetings/{id}/action-items/     GET list, POST add one
    /action-items/{id}/              PATCH / DELETE (flat)
    /meetings/{id}/ics/              GET → downloadable .ics calendar file

Visibility (§8 layer 2, queryset scoping): managers/admins see every
meeting; STAFF see meetings they organize or are invited to — an
out-of-scope meeting 404s, never 403s (don't leak existence). Writes on a
meeting (edit, lifecycle verbs, attendees, minutes) belong to the organizer
or a manager/admin; RSVP belongs to each attendee themselves.
"""

from django.db.models import Count, Q
from django.http import HttpResponse
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User
from apps.core.permissions import IsOwnerOrManager

from . import services
from .filters import MeetingFilter
from .models import ActionItem, Meeting, MeetingAttendee
from .serializers import (
    ActionItemSerializer,
    AttendeeCreateSerializer,
    AttendeeSerializer,
    CancelSerializer,
    MeetingDetailSerializer,
    MeetingListSerializer,
    MeetingWriteSerializer,
    MinutesSerializer,
    MinutesWriteSerializer,
    RescheduleSerializer,
    RespondSerializer,
)


def _is_manager(user):
    return user.role in (User.Role.ADMIN, User.Role.MANAGER)


class MeetingViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    owner_field = "organizer"  # read by IsOwnerOrManager: "owning" a meeting = organizing it
    http_method_names = ["get", "post", "patch", "put", "head", "options"]  # no delete — cancel
    filterset_class = MeetingFilter
    search_fields = ["title", "agenda", "client__name"]
    ordering_fields = ["scheduled_start", "created_at"]
    ordering = ["-scheduled_start"]

    def get_queryset(self):
        # §6 N+1 discipline: every FK the serializers touch is joined;
        # attendee_count arrives as one aggregate instead of a query per row.
        qs = (
            Meeting.objects.select_related("client", "project", "organizer", "cancelled_by")
            .prefetch_related("attendees__user", "attendees__contact", "reminders")
            .annotate(attendee_count=Count("attendees", distinct=True))
        )
        user = self.request.user
        if user.role == User.Role.STAFF:
            # §8 layer 2: scoping, not per-object checks — list/detail/actions
            # all stay consistent and out-of-scope meetings 404.
            qs = qs.filter(Q(organizer=user) | Q(attendees__user=user)).distinct()
        return qs

    def get_serializer_class(self):
        if self.action == "list":
            return MeetingListSerializer
        if self.action in ("create", "partial_update"):
            return MeetingWriteSerializer
        return MeetingDetailSerializer

    def get_permissions(self):
        perms = super().get_permissions()
        # Organizer-or-manager writes. For the GET/POST combo actions the
        # check applies only to the writing method — reading the attendee
        # list or the minutes needs only visibility (queryset scope).
        writing_combo = self.action in (
            "attendees",
            "minutes",
            "action_items",
        ) and self.request.method not in ("GET", "HEAD", "OPTIONS")
        if self.action in ("partial_update", "reschedule", "cancel", "complete", "no_show"):
            perms.append(IsOwnerOrManager())
        elif writing_combo:
            perms.append(IsOwnerOrManager())
        return perms

    def _detail(self, meeting, http_status=status.HTTP_200_OK):
        """Every mutation answers with the same full-detail shape."""
        # Re-fetch through get_queryset so the response carries the same
        # prefetched/annotated shape as a GET would.
        meeting = self.get_queryset().get(pk=meeting.pk)
        serializer = MeetingDetailSerializer(meeting, context=self.get_serializer_context())
        return Response(serializer.data, status=http_status)

    # -- create / update → services ------------------------------------------

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        # The collection inputs are not Meeting columns — pull them out
        # before building the model instance.
        user_attendees = data.pop("attendee_user_ids", [])
        contact_attendees = data.pop("attendee_contact_ids", [])
        reminder_offsets = data.pop("reminder_offsets", [])
        meeting = services.create_meeting(
            meeting=Meeting(**data),
            actor=request.user,
            user_attendees=user_attendees,
            contact_attendees=contact_attendees,
            reminder_offsets=reminder_offsets,
        )
        return self._detail(meeting, http_status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(instance, field, value)
        meeting = services.update_meeting(meeting=instance, actor=request.user)
        return self._detail(meeting)

    # -- lifecycle verbs ------------------------------------------------------

    @action(detail=True, methods=["post"])
    def reschedule(self, request, pk=None):
        meeting = self.get_object()
        serializer = RescheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._detail(
            services.reschedule_meeting(
                meeting=meeting,
                actor=request.user,
                start=serializer.validated_data["scheduled_start"],
                end=serializer.validated_data["scheduled_end"],
            )
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        meeting = self.get_object()
        serializer = CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._detail(
            services.cancel_meeting(
                meeting=meeting, actor=request.user, reason=serializer.validated_data["reason"]
            )
        )

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        return self._detail(
            services.complete_meeting(meeting=self.get_object(), actor=request.user)
        )

    @action(detail=True, methods=["post"], url_path="no-show")
    def no_show(self, request, pk=None):
        return self._detail(services.mark_no_show(meeting=self.get_object(), actor=request.user))

    # -- RSVP -----------------------------------------------------------------

    @action(detail=True, methods=["post"])
    def respond(self, request, pk=None):
        """Each attendee answers for THEMSELVES — no organizer permission."""
        meeting = self.get_object()
        serializer = RespondSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attendee = services.respond(
            meeting=meeting,
            user=request.user,
            response=serializer.validated_data["response"],
        )
        return Response(AttendeeSerializer(attendee).data)

    # -- attendees ------------------------------------------------------------

    @action(detail=True, methods=["get", "post"])
    def attendees(self, request, pk=None):
        meeting = self.get_object()
        if request.method == "GET":
            qs = meeting.attendees.select_related("user", "contact")
            return Response(AttendeeSerializer(qs, many=True).data)

        serializer = AttendeeCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attendee = services.add_attendee(
            meeting=meeting,
            actor=request.user,
            user=serializer.validated_data.get("user_id"),
            contact=serializer.validated_data.get("contact_id"),
            is_required=serializer.validated_data["is_required"],
        )
        return Response(AttendeeSerializer(attendee).data, status=status.HTTP_201_CREATED)

    # -- minutes of meeting ---------------------------------------------------

    @action(detail=True, methods=["get", "put"])
    def minutes(self, request, pk=None):
        meeting = self.get_object()
        if request.method == "GET":
            minutes = getattr(meeting, "minutes", None)
            if minutes is None:
                return Response(
                    {"detail": "No minutes recorded yet."}, status=status.HTTP_404_NOT_FOUND
                )
            return Response(MinutesSerializer(minutes).data)

        serializer = MinutesWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        minutes = services.save_minutes(
            meeting=meeting, actor=request.user, content=serializer.validated_data["content"]
        )
        return Response(MinutesSerializer(minutes).data)

    # -- action items ---------------------------------------------------------

    @action(detail=True, methods=["get", "post"], url_path="action-items")
    def action_items(self, request, pk=None):
        meeting = self.get_object()
        if request.method == "GET":
            qs = meeting.action_items.select_related("owner")
            return Response(ActionItemSerializer(qs, many=True).data)

        serializer = ActionItemSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = services.add_action_item(
            meeting=meeting,
            description=serializer.validated_data["description"],
            owner=serializer.validated_data.get("owner"),
            due_date=serializer.validated_data.get("due_date"),
        )
        return Response(ActionItemSerializer(item).data, status=status.HTTP_201_CREATED)

    # -- calendar integration -------------------------------------------------

    @action(detail=True, methods=["get"])
    def ics(self, request, pk=None):
        """Download the meeting as an .ics file (imports into any calendar)."""
        meeting = self.get_object()
        response = HttpResponse(services.build_ics(meeting), content_type="text/calendar")
        response["Content-Disposition"] = f'attachment; filename="meeting-{meeting.pk}.ics"'
        return response


class MeetingAttendeeViewSet(mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """Flat delete (§6: nested read/create, flat destroy)."""

    serializer_class = AttendeeSerializer

    def get_queryset(self):
        qs = MeetingAttendee.objects.select_related("meeting", "user", "contact")
        user = self.request.user
        if not _is_manager(user):
            # Staff may only manage the list of meetings they organize —
            # scoping again, so foreign attendee rows simply 404.
            qs = qs.filter(meeting__organizer=user)
        return qs

    def perform_destroy(self, instance):
        services.remove_attendee(attendee=instance, actor=self.request.user)


class ActionItemViewSet(mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """
    Flat PATCH (tick done, reassign, move due date) / DELETE. Scope: managers
    everything; staff items on their own meetings PLUS items they own — the
    person on the hook must be able to tick their item done.
    """

    serializer_class = ActionItemSerializer
    http_method_names = ["patch", "delete", "head", "options"]

    def get_queryset(self):
        qs = ActionItem.objects.select_related("owner", "meeting")
        user = self.request.user
        if not _is_manager(user):
            qs = qs.filter(Q(meeting__organizer=user) | Q(owner=user)).distinct()
        return qs
