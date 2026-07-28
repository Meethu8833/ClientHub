"""
Auth API (ARCHITECTURE.md §7).

Token placement contract:
- access token  -> response body, kept in React memory, sent as
                   `Authorization: Bearer <access>` (15 min lifetime).
- refresh token -> HttpOnly cookie scoped to /api/v1/auth/ (7 days).
  JavaScript can never read it, so an XSS can't exfiltrate it.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import generics, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.audit import services as audit_services
from apps.audit.models import AuditLog

from . import services
from .serializers import (
    ChangePasswordSerializer,
    ForgotPasswordSerializer,
    LoginSerializer,
    ResetPasswordSerializer,
    UserSerializer,
    VerifyEmailSerializer,
)

User = get_user_model()


def set_refresh_cookie(response, refresh_token):
    """Attach the refresh token as an HttpOnly cookie on the response."""
    response.set_cookie(
        settings.REFRESH_TOKEN_COOKIE,
        refresh_token,
        max_age=int(settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()),
        path=settings.REFRESH_TOKEN_COOKIE_PATH,  # only sent to /api/v1/auth/*
        httponly=True,  # invisible to document.cookie / JS
        secure=settings.REFRESH_TOKEN_COOKIE_SECURE,
        samesite=settings.REFRESH_TOKEN_COOKIE_SAMESITE,
    )


def clear_refresh_cookie(response):
    """Expire the cookie (path must match the one used to set it)."""
    response.delete_cookie(settings.REFRESH_TOKEN_COOKIE, path=settings.REFRESH_TOKEN_COOKIE_PATH)


class LoginView(TokenObtainPairView):
    """
    POST /api/v1/auth/login/   {email, password}
    -> 200 {access, user} + Set-Cookie: refresh_token (HttpOnly)
    -> 401 on bad credentials (same message whether email exists or not)
    """

    serializer_class = LoginSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        # SimpleJWT put both tokens in the body; move refresh into the cookie.
        set_refresh_cookie(response, response.data.pop("refresh"))
        return response


class RefreshView(TokenRefreshView):
    """
    POST /api/v1/auth/refresh/   (no body — browser sends the cookie)
    -> 200 {access} + rotated refresh cookie (old one blacklisted)
    -> 401 if the cookie is missing, expired, or blacklisted
    """

    def post(self, request, *args, **kwargs):
        # `not refresh` (not `is None`): a deleted cookie can arrive as "".
        refresh = request.COOKIES.get(settings.REFRESH_TOKEN_COOKIE)
        if not refresh:
            raise InvalidToken("No refresh token cookie.")

        serializer = self.get_serializer(data={"refresh": refresh})
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0]) from e

        data = serializer.validated_data
        # ROTATE_REFRESH_TOKENS=True → a new refresh token is issued each time.
        new_refresh = data.pop("refresh", None)
        response = Response(data)
        if new_refresh:
            set_refresh_cookie(response, new_refresh)
        return response


class LogoutView(APIView):
    """
    POST /api/v1/auth/logout/ -> 200, refresh token blacklisted, cookie cleared.

    AllowAny on purpose: logout must still work when the access token has
    already expired — the cookie alone is enough to revoke the session.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        refresh = request.COOKIES.get(settings.REFRESH_TOKEN_COOKIE)
        if refresh:
            try:
                token = RefreshToken(refresh)
                token.blacklist()
            except TokenError:
                pass  # already expired/blacklisted — logout is still a success
            else:
                # request.user may be anonymous here (AllowAny + expired
                # access token), but the refresh token's user_id claim tells
                # us whose session was just revoked.
                audit_services.log(
                    action=AuditLog.Action.LOGOUT,
                    actor=User.objects.filter(pk=token.payload.get("user_id")).first(),
                )
        response = Response({"detail": "Logged out."})
        clear_refresh_cookie(response)
        return response


class MeView(generics.RetrieveUpdateAPIView):
    """
    GET   /api/v1/auth/me/  -> the logged-in user's profile
    PATCH /api/v1/auth/me/  -> update first_name / last_name
    """

    serializer_class = UserSerializer
    # PATCH (partial) only — PUT would demand every writable field each time.
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        # No pk in the URL: "me" is always the authenticated caller, so users
        # can never address (or update) anyone else's profile here.
        return self.request.user


class ChangePasswordView(APIView):
    """
    POST /api/v1/auth/change-password/  {current_password, new_password}
    Requires login. Afterwards every refresh token is revoked (all devices),
    and a fresh cookie is issued so THIS device stays logged in.
    """

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])

        services.revoke_all_refresh_tokens(user)
        response = Response({"detail": "Password changed."})
        set_refresh_cookie(response, str(RefreshToken.for_user(user)))
        return response


class ForgotPasswordView(APIView):
    """
    POST /api/v1/auth/forgot-password/  {email}
    Always answers 200 with the same message — the response must not reveal
    whether an account exists (user-enumeration defense).
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = User.objects.filter(
            email__iexact=serializer.validated_data["email"], is_active=True
        ).first()
        if user:
            services.send_password_reset_email(user)

        return Response(
            {"detail": "If an account with that email exists, a reset link has been sent."}
        )


class ResetPasswordView(APIView):
    """
    POST /api/v1/auth/reset-password/  {uid, token, new_password}
    Consumes the emailed link. On success all existing sessions are revoked;
    the user then logs in with the new password.
    """

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        services.revoke_all_refresh_tokens(user)

        return Response({"detail": "Password has been reset. Please log in."})


class SendVerificationEmailView(APIView):
    """POST /api/v1/auth/send-verification-email/ — (re)send the link. Requires login."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "email_verification"

    def post(self, request):
        if request.user.is_email_verified:
            return Response({"detail": "Email is already verified."})
        services.send_verification_email(request.user)
        return Response({"detail": "Verification email sent."})


class VerifyEmailView(APIView):
    """
    POST /api/v1/auth/verify-email/  {token}
    AllowAny: the user clicks the email link possibly on a device where they
    aren't logged in — the signed token itself proves identity.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_id = services.read_email_verification_token(serializer.validated_data["token"])
        user = User.objects.filter(pk=user_id, is_active=True).first() if user_id else None
        if user is None:
            return Response(
                {"detail": "Invalid or expired verification link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not user.is_email_verified:
            user.is_email_verified = True
            user.save(update_fields=["is_email_verified"])
        return Response({"detail": "Email verified."})
