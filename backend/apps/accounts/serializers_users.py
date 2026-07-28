"""
User-management serializers (admin API at /api/v1/users/).

Separate serializers per operation — list vs detail vs create vs update —
instead of one do-everything class (ARCHITECTURE.md §6): each endpoint
exposes exactly the fields it needs and nothing more.
"""

from django.contrib.auth import get_user_model, password_validation
from rest_framework import serializers

User = get_user_model()

AVATAR_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
AVATAR_ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


class AssignableUserSerializer(serializers.ModelSerializer):
    """
    Dropdown-option shape for pickers (client account manager, task assignee…).
    Deliberately tiny: managers may fetch this list, so it must not expose the
    admin-only fields (is_active, last_login, …) the other shapes carry.
    """

    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "name", "email", "role"]

    def get_name(self, obj):
        return obj.get_full_name() or obj.email


class UserListSerializer(serializers.ModelSerializer):
    """Slim row for the users table — only what the list screen renders."""

    full_name = serializers.CharField(source="get_full_name", read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "role", "is_active", "avatar", "date_joined"]


class UserDetailSerializer(serializers.ModelSerializer):
    """Full read shape for GET /users/{id}/ (everything safe to show an admin)."""

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "role",
            "avatar",
            "is_active",
            "is_email_verified",
            "weekly_capacity_hours",
            "date_joined",
            "last_login",
        ]


class UserCreateSerializer(serializers.ModelSerializer):
    """
    Admin creates a user. Two supported flows:
    - password given  -> account usable immediately (admin hands it over).
    - password omitted -> account created with an UNUSABLE password and the
      view emails an invite (our password-reset link) so the user sets their
      own password — nobody but them ever knows it. Preferred in production.
    """

    # write_only: accepted as input, never echoed back in the response.
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "role", "password"]

    def validate_email(self, value):
        # unique=True on the model already rejects exact duplicates, but only
        # case-sensitively: Ana@x.com and ana@x.com would both get in. Emails
        # are case-insensitive in practice, so normalize and check ourselves.
        value = value.lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_password(self, value):
        # Same strength rules as everywhere else (AUTH_PASSWORD_VALIDATORS).
        password_validation.validate_password(value)
        return value

    def create(self, validated_data):
        # create_user (not User.objects.create!) hashes the password; with
        # password=None it stores an unusable hash that can never log in
        # until the invite flow sets a real one.
        password = validated_data.pop("password", None)
        return User.objects.create_user(password=password, **validated_data)


class UserUpdateSerializer(serializers.ModelSerializer):
    """
    PATCH /users/{id}/ — names + contracted hours only, on purpose:
    - email is the login identifier; changing it needs re-verification (later).
    - role changes go through the dedicated assign-role action (audited, guarded).
    - is_active flips through activate/deactivate (they also revoke sessions).
    weekly_capacity_hours feeds capacity planning (teams app) — admin-managed
    operational data, so it belongs on this admin-only endpoint.
    """

    class Meta:
        model = User
        fields = ["first_name", "last_name", "weekly_capacity_hours"]


class AssignRoleSerializer(serializers.Serializer):
    """Body of POST /users/{id}/assign-role/. ChoiceField 400s on unknown roles."""

    role = serializers.ChoiceField(choices=User.Role.choices)


class AvatarSerializer(serializers.ModelSerializer):
    """
    PUT /users/{id}/avatar/ (multipart). ImageField + Pillow already verify
    the bytes decode as a real image; we add size and extension limits.
    """

    avatar = serializers.ImageField(required=True)

    class Meta:
        model = User
        fields = ["avatar"]

    def validate_avatar(self, value):
        if value.size > AVATAR_MAX_BYTES:
            raise serializers.ValidationError("Image is too large (max 2 MB).")
        ext = value.name.rsplit(".", 1)[-1].lower() if "." in value.name else ""
        if ext not in AVATAR_ALLOWED_EXTENSIONS:
            allowed = ", ".join(sorted(AVATAR_ALLOWED_EXTENSIONS))
            raise serializers.ValidationError(f"Unsupported file type. Allowed: {allowed}.")
        return value
