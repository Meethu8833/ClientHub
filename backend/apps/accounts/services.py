"""
Auth side-effects: emails, one-time tokens, refresh-token revocation.

Views call these functions; the functions never touch request/response objects.
That separation keeps views thin and makes this logic unit-testable on its own.
"""

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.mail import send_mail
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

# Salt namespaces the signature: a token signed for email verification can
# never be replayed against some other signing-based feature.
EMAIL_VERIFICATION_SALT = "accounts.email-verification"


def send_password_reset_email(user):
    """Email a one-time reset link pointing at the React reset page."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"

    send_mail(
        subject="Reset your ClientHub password",
        message=(
            f"Hi {user.first_name or user.email},\n\n"
            f"Someone requested a password reset for your ClientHub account.\n"
            f"If this was you, open the link below (valid for 1 hour):\n\n{link}\n\n"
            f"If it wasn't you, ignore this email — your password is unchanged."
        ),
        from_email=None,  # falls back to DEFAULT_FROM_EMAIL
        recipient_list=[user.email],
    )


def make_email_verification_token(user):
    """Signed, expiring token that encodes which user is being verified."""
    return signing.dumps({"user_id": user.pk}, salt=EMAIL_VERIFICATION_SALT)


def read_email_verification_token(token):
    """Return the user_id inside a valid token, or None (tampered/expired)."""
    try:
        payload = signing.loads(
            token,
            salt=EMAIL_VERIFICATION_SALT,
            max_age=settings.EMAIL_VERIFICATION_TIMEOUT,
        )
    except signing.BadSignature:  # SignatureExpired subclasses BadSignature
        return None
    return payload.get("user_id")


def send_verification_email(user):
    """Email a link that proves the user controls this inbox."""
    token = make_email_verification_token(user)
    link = f"{settings.FRONTEND_URL}/verify-email?token={token}"

    send_mail(
        subject="Verify your ClientHub email address",
        message=(
            f"Hi {user.first_name or user.email},\n\n"
            f"Confirm this is your email address by opening the link below "
            f"(valid for 24 hours):\n\n{link}"
        ),
        from_email=None,
        recipient_list=[user.email],
    )


# --------------------------------------------------------------------------
# User management (admin API) — every state change that has side effects
# lives here so views stay thin and the rules are unit-testable.
# --------------------------------------------------------------------------


def send_invite_email(user):
    """
    Invite a freshly created user (no password yet) to set their own.
    Reuses the password-reset token machinery — same link, same security.
    """
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"

    send_mail(
        subject="You've been invited to ClientHub",
        message=(
            f"Hi {user.first_name or user.email},\n\n"
            f"An administrator created a ClientHub account for you.\n"
            f"Set your password here (link valid for 1 hour):\n\n{link}"
        ),
        from_email=None,
        recipient_list=[user.email],
    )


def deactivate_user(user):
    """
    Reversible block: user disappears from login but keeps all data.
    Revoking refresh tokens matters — is_active=False stops NEW logins,
    but a live refresh token could still mint access tokens for days.
    """
    user.is_active = False
    user.save(update_fields=["is_active"])
    revoke_all_refresh_tokens(user)


def activate_user(user):
    user.is_active = True
    user.save(update_fields=["is_active"])


def soft_delete_user(user):
    """
    Soft delete: stamp deleted_at, block login, kill sessions — but KEEP the
    row, so every FK pointing at this user (clients managed, tasks, time
    entries) stays valid and history remains auditable.
    """
    user.deleted_at = timezone.now()
    user.is_active = False
    user.save(update_fields=["deleted_at", "is_active"])
    revoke_all_refresh_tokens(user)


def assign_role(user, role):
    user.role = role
    user.save(update_fields=["role"])


def set_avatar(user, image):
    """Replace the profile picture, deleting the old file (no orphans on disk)."""
    if user.avatar:
        user.avatar.delete(save=False)  # removes the file, not the row
    user.avatar = image
    user.save(update_fields=["avatar"])


def remove_avatar(user):
    if user.avatar:
        user.avatar.delete(save=False)
        user.avatar = None
        user.save(update_fields=["avatar"])


def revoke_all_refresh_tokens(user):
    """
    Blacklist every outstanding refresh token for a user.

    Called after password change/reset: JWTs are stateless, so without this a
    thief holding a refresh token could keep minting access tokens even after
    the victim changed their password.
    """
    for outstanding in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=outstanding)
