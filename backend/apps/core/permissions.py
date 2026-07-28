"""
Role-based permission classes (ARCHITECTURE.md §8, layer 1).

Authentication answers "who are you?" — these answer "are you ALLOWED?".
DRF calls has_permission() before the view body runs; returning False
produces 403 Forbidden (or 401 if the caller isn't authenticated at all).

Composable with | and &:  permission_classes = [IsAuthenticated & IsManagerOrAdmin]
Layer 2 (object scoping for STAFF) is queryset filtering, not classes — see §8.
"""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.models import User


class IsAdmin(BasePermission):
    """Admins only (user management, global settings)."""

    def has_permission(self, request, view):
        return bool(request.user.is_authenticated and request.user.role == User.Role.ADMIN)


class IsManagerOrAdmin(BasePermission):
    """Managers and admins (create/delete projects, manage clients…)."""

    def has_permission(self, request, view):
        return bool(
            request.user.is_authenticated
            and request.user.role in (User.Role.ADMIN, User.Role.MANAGER)
        )


class ReadOnlyForStaff(BasePermission):
    """
    STAFF may only use safe methods (GET/HEAD/OPTIONS); managers/admins may write.
    Used by e.g. the clients endpoints where staff can look but not touch.
    """

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return request.user.role in (User.Role.ADMIN, User.Role.MANAGER)


class IsOwnerOrManager(BasePermission):
    """
    Object-level check: staff may modify only records they own.
    The view tells us which attribute points at the owner via
    `owner_field` (default "owner").
    """

    def has_object_permission(self, request, view, obj):
        if request.user.role in (User.Role.ADMIN, User.Role.MANAGER):
            return True
        owner_field = getattr(view, "owner_field", "owner")
        return getattr(obj, owner_field, None) == request.user
