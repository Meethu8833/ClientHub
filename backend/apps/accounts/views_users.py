"""
User-management API: /api/v1/users/ (admin only, ARCHITECTURE.md §6 + §8)
plus the self-service avatar endpoint mounted at /api/v1/auth/me/avatar/.

One ModelViewSet supplies list/retrieve/create/update/delete; lifecycle
verbs (activate, deactivate, assign-role, avatar) are @action routes UNDER
the resource — never top-level RPC URLs.
"""

from django.contrib.auth import get_user_model
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAdmin, IsManagerOrAdmin

from . import services
from .filters import UserFilter
from .serializers_users import (
    AssignableUserSerializer,
    AssignRoleSerializer,
    AvatarSerializer,
    UserCreateSerializer,
    UserDetailSerializer,
    UserListSerializer,
    UserUpdateSerializer,
)

User = get_user_model()


class UserViewSet(viewsets.ModelViewSet):
    """
    GET    /users/                list (search / filter / sort / paginate)
    POST   /users/                create (invite email if no password given)
    GET    /users/{id}/           detail
    PATCH  /users/{id}/           update names
    DELETE /users/{id}/           SOFT delete
    POST   /users/{id}/deactivate/  block login, keep in lists (reversible)
    POST   /users/{id}/activate/
    POST   /users/{id}/assign-role/ {"role": "manager"}
    PUT    /users/{id}/avatar/    multipart upload
    DELETE /users/{id}/avatar/
    """

    permission_classes = [IsAdmin]
    filterset_class = UserFilter
    search_fields = ["email", "first_name", "last_name"]
    # Whitelist for ?ordering= — anything else is silently ignored by DRF.
    ordering_fields = ["email", "first_name", "last_name", "role", "date_joined", "last_login"]
    ordering = ["-date_joined"]  # default; also keeps pagination deterministic

    def get_queryset(self):
        # Soft-deleted users are invisible to the whole API: list, detail,
        # update and delete all flow through this queryset, so an out-of-
        # scope id consistently 404s instead of leaking existence.
        return User.objects.alive()

    def get_serializer_class(self):
        return {
            "list": UserListSerializer,
            "create": UserCreateSerializer,
            "partial_update": UserUpdateSerializer,
            "assign_role": AssignRoleSerializer,
            "avatar": AvatarSerializer,
        }.get(self.action, UserDetailSerializer)

    # ---------------------------------------------------------------- guards

    def _guard_not_self(self, user, verb):
        """An admin never locks themselves out by acting on their own account."""
        if user == self.request.user:
            raise PermissionDenied(f"You cannot {verb} your own account.")

    def _guard_not_last_admin(self, user, verb):
        """
        Refuse to remove the final active admin — otherwise nobody is left
        who can manage users, and recovery means shell access to the server.
        """
        is_last_admin = (
            user.role == User.Role.ADMIN
            and not User.objects.alive()
            .filter(role=User.Role.ADMIN, is_active=True)
            .exclude(pk=user.pk)
            .exists()
        )
        if is_last_admin:
            raise ValidationError({"detail": f"Cannot {verb} the last active admin."})

    # ------------------------------------------------------------------ CRUD

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        if not user.has_usable_password():  # no password supplied -> invite flow
            services.send_invite_email(user)
        data = UserDetailSerializer(user, context=self.get_serializer_context()).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        # PATCH only. We can't use http_method_names to ban PUT — that gates
        # the WHOLE viewset and would break the PUT avatar action too.
        if not kwargs.get("partial"):
            raise MethodNotAllowed("PUT")
        # Validate with the slim write serializer, respond with the full
        # detail shape so the frontend can refresh its row from the response.
        response = super().update(request, *args, **kwargs)
        detail = UserDetailSerializer(self.get_object(), context=self.get_serializer_context())
        response.data = detail.data
        return response

    def destroy(self, request, *args, **kwargs):
        user = self.get_object()
        self._guard_not_self(user, "delete")
        self._guard_not_last_admin(user, "delete")
        services.soft_delete_user(user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    # --------------------------------------------------------------- actions

    @action(
        detail=False,
        methods=["get"],
        permission_classes=[IsManagerOrAdmin],  # overrides the class-level IsAdmin
        filter_backends=[],  # no search/ordering — the picker filters client-side
        pagination_class=None,  # a dropdown needs the whole list at once
    )
    def assignable(self, request):
        """
        GET /users/assignable/ — the option list for user pickers (e.g. a
        client's account manager). Managers create clients but must not see
        the admin user screens, hence the wider permission + narrower shape.
        Mirrors ClientWriteSerializer's account_manager queryset (alive users)
        so the dropdown can never offer an id the write would then reject.
        """
        users = User.objects.alive().order_by("first_name", "last_name", "email")
        return Response(AssignableUserSerializer(users, many=True).data)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        user = self.get_object()
        self._guard_not_self(user, "deactivate")
        self._guard_not_last_admin(user, "deactivate")
        services.deactivate_user(user)
        return Response(UserDetailSerializer(user, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        user = self.get_object()
        services.activate_user(user)
        return Response(UserDetailSerializer(user, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="assign-role")
    def assign_role(self, request, pk=None):
        user = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_role = serializer.validated_data["role"]

        self._guard_not_self(user, "change the role of")
        if user.role == User.Role.ADMIN and new_role != User.Role.ADMIN:
            self._guard_not_last_admin(user, "demote")

        services.assign_role(user, new_role)
        return Response(UserDetailSerializer(user, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["put", "delete"], parser_classes=[MultiPartParser, FormParser])
    def avatar(self, request, pk=None):
        user = self.get_object()
        if request.method == "DELETE":
            services.remove_avatar(user)
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_avatar(user, serializer.validated_data["avatar"])
        return Response(AvatarSerializer(user, context=self.get_serializer_context()).data)


class MeAvatarView(APIView):
    """
    PUT/DELETE /api/v1/auth/me/avatar/ — any logged-in user manages their OWN
    picture. Same serializer and services as the admin action; the only
    difference is the target is always request.user (no id to tamper with).
    """

    parser_classes = [MultiPartParser, FormParser]

    def put(self, request):
        serializer = AvatarSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_avatar(request.user, serializer.validated_data["avatar"])
        return Response(AvatarSerializer(request.user, context={"request": request}).data)

    def delete(self, request):
        services.remove_avatar(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
