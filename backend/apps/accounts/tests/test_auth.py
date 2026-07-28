"""
Auth endpoint tests: every endpoint's happy path + its permission/failure edges.

The Django test client stores Set-Cookie values on `client.cookies`, so after
login the refresh cookie is sent automatically on later requests — exactly
like a browser.
"""

import re

import pytest
from django.conf import settings
from django.core import mail
from django.urls import reverse
from rest_framework.test import APIClient

from apps.accounts.models import User

PASSWORD = "Str0ng!pass123"
NEW_PASSWORD = "N3w!password456"

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user(
        email="ana@example.com", password=PASSWORD, first_name="Ana", role=User.Role.STAFF
    )


@pytest.fixture
def api():
    return APIClient()


def login(api, email="ana@example.com", password=PASSWORD):
    return api.post(
        reverse("accounts:login"), {"email": email, "password": password}, format="json"
    )


def auth(api, access):
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")


# ---------------------------------------------------------------- login


def test_login_returns_access_user_and_refresh_cookie(api, user):
    response = login(api)

    assert response.status_code == 200
    assert "access" in response.data
    assert response.data["user"]["email"] == "ana@example.com"
    assert response.data["user"]["role"] == "staff"
    # refresh must be in the HttpOnly cookie, never in the body
    assert "refresh" not in response.data
    cookie = response.cookies[settings.REFRESH_TOKEN_COOKIE]
    assert cookie["httponly"]
    assert cookie["path"] == settings.REFRESH_TOKEN_COOKIE_PATH


def test_login_wrong_password_is_401_with_generic_message(api, user):
    response = login(api, password="wrong-password")
    assert response.status_code == 401


def test_login_unknown_email_same_response_as_wrong_password(api, user):
    wrong_pw = login(api, password="wrong-password")
    unknown = login(api, email="ghost@example.com")
    # identical status + detail → no user enumeration
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.data == unknown.data


# ---------------------------------------------------------------- refresh


def test_refresh_returns_new_access_and_rotates_cookie(api, user):
    old_refresh = login(api).cookies[settings.REFRESH_TOKEN_COOKIE].value

    response = api.post(reverse("accounts:refresh"))

    assert response.status_code == 200
    assert "access" in response.data
    new_refresh = response.cookies[settings.REFRESH_TOKEN_COOKIE].value
    assert new_refresh and new_refresh != old_refresh


def test_rotated_out_refresh_token_is_blacklisted(api, user):
    old_refresh = login(api).cookies[settings.REFRESH_TOKEN_COOKIE].value
    api.post(reverse("accounts:refresh"))  # rotation blacklists old_refresh

    api.cookies[settings.REFRESH_TOKEN_COOKIE] = old_refresh  # attacker replays it
    assert api.post(reverse("accounts:refresh")).status_code == 401


def test_refresh_without_cookie_is_401(api, user):
    assert api.post(reverse("accounts:refresh")).status_code == 401


# ---------------------------------------------------------------- logout


def test_logout_blacklists_refresh_and_clears_cookie(api, user):
    login(api)

    response = api.post(reverse("accounts:logout"))

    assert response.status_code == 200
    assert response.cookies[settings.REFRESH_TOKEN_COOKIE].value == ""  # deleted
    # the blacklisted token can no longer refresh even if replayed
    assert api.post(reverse("accounts:refresh")).status_code == 401


def test_logout_without_cookie_still_succeeds(api):
    assert api.post(reverse("accounts:logout")).status_code == 200


# ---------------------------------------------------------------- me


def test_me_requires_authentication(api, user):
    assert api.get(reverse("accounts:me")).status_code == 401


def test_me_returns_profile(api, user):
    auth(api, login(api).data["access"])

    response = api.get(reverse("accounts:me"))

    assert response.status_code == 200
    assert response.data["email"] == "ana@example.com"
    assert response.data["is_email_verified"] is False


def test_me_patch_updates_name_but_not_role(api, user):
    auth(api, login(api).data["access"])

    response = api.patch(
        reverse("accounts:me"), {"first_name": "Anna", "role": "admin"}, format="json"
    )

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.first_name == "Anna"
    assert user.role == User.Role.STAFF  # read-only field silently ignored


# ---------------------------------------------------------------- change password


def test_change_password_rejects_wrong_current_password(api, user):
    auth(api, login(api).data["access"])

    response = api.post(
        reverse("accounts:change-password"),
        {"current_password": "nope", "new_password": NEW_PASSWORD},
        format="json",
    )

    assert response.status_code == 400
    assert "current_password" in response.data


def test_change_password_rejects_weak_new_password(api, user):
    auth(api, login(api).data["access"])

    response = api.post(
        reverse("accounts:change-password"),
        {"current_password": PASSWORD, "new_password": "123"},
        format="json",
    )

    assert response.status_code == 400
    assert "new_password" in response.data


def test_change_password_revokes_old_sessions_but_keeps_this_one(api, user):
    old_refresh = login(api).cookies[settings.REFRESH_TOKEN_COOKIE].value
    auth(api, api.post(reverse("accounts:refresh")).data["access"])

    response = api.post(
        reverse("accounts:change-password"),
        {"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        format="json",
    )
    assert response.status_code == 200

    # this device got a fresh cookie and can still refresh
    assert api.post(reverse("accounts:refresh")).status_code == 200
    # any other device's refresh token is dead
    api.cookies[settings.REFRESH_TOKEN_COOKIE] = old_refresh
    assert api.post(reverse("accounts:refresh")).status_code == 401
    # and the new password is the one that works now
    fresh = APIClient()
    assert login(fresh, password=PASSWORD).status_code == 401
    assert login(fresh, password=NEW_PASSWORD).status_code == 200


# ---------------------------------------------------------------- forgot / reset


def _reset_link_parts(email_body):
    match = re.search(r"reset-password\?uid=([^&\s]+)&token=([^\s]+)", email_body)
    assert match, f"no reset link in email:\n{email_body}"
    return match.group(1), match.group(2)


def test_forgot_password_sends_email_for_existing_account(api, user):
    response = api.post(
        reverse("accounts:forgot-password"), {"email": "ana@example.com"}, format="json"
    )

    assert response.status_code == 200
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["ana@example.com"]


def test_forgot_password_gives_identical_response_for_unknown_email(api, user):
    known = api.post(
        reverse("accounts:forgot-password"), {"email": "ana@example.com"}, format="json"
    )
    unknown = api.post(
        reverse("accounts:forgot-password"), {"email": "ghost@example.com"}, format="json"
    )

    assert known.data == unknown.data  # no enumeration
    assert len(mail.outbox) == 1  # only the real account got an email


def test_reset_password_full_flow(api, user):
    api.post(reverse("accounts:forgot-password"), {"email": "ana@example.com"}, format="json")
    uid, token = _reset_link_parts(mail.outbox[0].body)

    response = api.post(
        reverse("accounts:reset-password"),
        {"uid": uid, "token": token, "new_password": NEW_PASSWORD},
        format="json",
    )

    assert response.status_code == 200
    assert login(api, password=NEW_PASSWORD).status_code == 200
    assert login(api, password=PASSWORD).status_code == 401


def test_reset_token_is_single_use(api, user):
    api.post(reverse("accounts:forgot-password"), {"email": "ana@example.com"}, format="json")
    uid, token = _reset_link_parts(mail.outbox[0].body)
    payload = {"uid": uid, "token": token, "new_password": NEW_PASSWORD}

    assert api.post(reverse("accounts:reset-password"), payload, format="json").status_code == 200
    # same link again: the password hash changed, so the token no longer checks out
    assert api.post(reverse("accounts:reset-password"), payload, format="json").status_code == 400


def test_reset_password_rejects_tampered_token(api, user):
    response = api.post(
        reverse("accounts:reset-password"),
        {"uid": "abc", "token": "fake-token", "new_password": NEW_PASSWORD},
        format="json",
    )
    assert response.status_code == 400


# ---------------------------------------------------------------- email verification


def _verification_token(email_body):
    match = re.search(r"verify-email\?token=([^\s]+)", email_body)
    assert match, f"no verification link in email:\n{email_body}"
    return match.group(1)


def test_email_verification_full_flow(api, user):
    auth(api, login(api).data["access"])

    send = api.post(reverse("accounts:send-verification-email"))
    assert send.status_code == 200
    token = _verification_token(mail.outbox[0].body)

    # verification link may be opened logged-out — use a clean client
    verify = APIClient().post(reverse("accounts:verify-email"), {"token": token}, format="json")

    assert verify.status_code == 200
    user.refresh_from_db()
    assert user.is_email_verified is True


def test_send_verification_requires_login(api, user):
    assert api.post(reverse("accounts:send-verification-email")).status_code == 401


def test_verify_email_rejects_garbage_token(api, user):
    response = api.post(reverse("accounts:verify-email"), {"token": "garbage"}, format="json")
    assert response.status_code == 400
