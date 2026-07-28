"""
Serializers = the API's validation & shaping layer.

Every byte that enters or leaves the auth API passes through one of these:
they validate input (types, required fields, password strength) and control
exactly which User fields are exposed — never "everything the model has".
"""

from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from apps.audit import services as audit_services
from apps.audit.models import AuditLog

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Public shape of a user. Used by /me/ and embedded in the login response."""

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "role",
            "avatar",
            "is_email_verified",
            "date_joined",
            "last_login",
        ]
        # Only names are editable through the API. Email is the login identifier
        # (changing it must go through re-verification — a later feature), and
        # role is assigned by admins, never self-assigned.
        read_only_fields = ["id", "email", "role", "is_email_verified", "date_joined", "last_login"]


class LoginSerializer(TokenObtainPairSerializer):
    """
    SimpleJWT's login serializer, extended two ways:
    1. Extra claims inside the access token (role) so the backend — and the
       React app, which can decode the payload — knows the role without a
       second request.
    2. The serialized user in the response body, so the frontend can populate
       its auth context from the login call alone.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["email"] = user.email
        return token

    def validate(self, attrs):
        data = super().validate(attrs)  # -> {"access": ..., "refresh": ...}
        data["user"] = UserSerializer(self.user).data
        # Audit successful logins here, not via Django's user_logged_in
        # signal: SimpleJWT never calls auth.login() (no session is created),
        # so that signal never fires for JWT. actor is passed explicitly —
        # request.user is still anonymous during the login call itself.
        audit_services.log(
            action=AuditLog.Action.LOGIN,
            actor=self.user,
            request=self.context.get("request"),
        )
        return data


class ChangePasswordSerializer(serializers.Serializer):
    """For logged-in users. Requires the current password (stolen-session guard)."""

    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        # Runs AUTH_PASSWORD_VALIDATORS (length, common-password, similarity…).
        password_validation.validate_password(value, self.context["request"].user)
        return value


class ForgotPasswordSerializer(serializers.Serializer):
    """Only validates the email format — existence is checked (silently) in the view."""

    email = serializers.EmailField()


class ResetPasswordSerializer(serializers.Serializer):
    """
    Consumes the credentials from the emailed link:
    uid   – user's primary key, base64-encoded (identifies WHO)
    token – Django one-time reset token (proves the email was received)
    """

    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        try:
            user_id = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=user_id, is_active=True)
        except (ValueError, TypeError, OverflowError, User.DoesNotExist):
            # `from None` hides the internal exception chain from error handling
            raise serializers.ValidationError({"uid": "Invalid reset link."}) from None

        # check_token re-derives the hash; it fails if the token expired, was
        # already used (password hash changed), or belongs to another user.
        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError({"token": "Invalid or expired reset link."})

        password_validation.validate_password(attrs["new_password"], user)
        attrs["user"] = user
        return attrs


class VerifyEmailSerializer(serializers.Serializer):
    """The signed token from the verification email link."""

    token = serializers.CharField()
