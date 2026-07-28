"""
User-management API tests: every endpoint's happy path, every role's
permission boundary, and the lifecycle guards (self-action, last admin).
"""

import io
import os

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from rest_framework.test import APIClient
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.accounts.views_users import UserViewSet

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db

LIST_URL = reverse("users:user-list")


def detail_url(user_id):
    return reverse("users:user-detail", args=[user_id])


@pytest.fixture
def admin():
    return User.objects.create_user(
        email="admin@example.com", password=PASSWORD, first_name="Ada", role=User.Role.ADMIN
    )


@pytest.fixture
def manager():
    return User.objects.create_user(
        email="manager@example.com", password=PASSWORD, first_name="Max", role=User.Role.MANAGER
    )


@pytest.fixture
def staff():
    return User.objects.create_user(
        email="staff@example.com", password=PASSWORD, first_name="Stan", role=User.Role.STAFF
    )


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def admin_api(api, admin):
    # force_authenticate skips the JWT dance — token mechanics are already
    # covered in test_auth.py; here we only care about permissions/behavior.
    api.force_authenticate(user=admin)
    return api


def make_image(name="avatar.png", size=(10, 10), fmt="PNG"):
    """A real, tiny in-memory image (Pillow must be able to decode uploads)."""
    buf = io.BytesIO()
    Image.new("RGB", size, color=(120, 40, 200)).save(buf, format=fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=f"image/{fmt.lower()}")


# ------------------------------------------------------------- permissions


def test_anonymous_gets_401(api):
    assert api.get(LIST_URL).status_code == 401


@pytest.mark.parametrize("role_fixture", ["manager", "staff"])
def test_non_admin_gets_403(api, role_fixture, request):
    api.force_authenticate(user=request.getfixturevalue(role_fixture))
    assert api.get(LIST_URL).status_code == 403
    assert api.post(LIST_URL, {}).status_code == 403


def test_admin_can_list(admin_api):
    response = admin_api.get(LIST_URL)
    assert response.status_code == 200
    assert {"count", "next", "previous", "results"} <= set(response.data)


# ------------------------------------------------- list / search / filters


def test_list_excludes_soft_deleted(admin_api, staff):
    from apps.accounts import services

    services.soft_delete_user(staff)
    emails = [row["email"] for row in admin_api.get(LIST_URL).data["results"]]
    assert staff.email not in emails


def test_search_matches_name_and_email(admin_api, manager, staff):
    results = admin_api.get(LIST_URL, {"search": "Stan"}).data["results"]
    assert [row["email"] for row in results] == [staff.email]


def test_filter_by_role(admin_api, manager, staff):
    results = admin_api.get(LIST_URL, {"role": "manager"}).data["results"]
    assert [row["email"] for row in results] == [manager.email]


def test_filter_by_is_active(admin_api, staff):
    staff.is_active = False
    staff.save()
    results = admin_api.get(LIST_URL, {"is_active": "false"}).data["results"]
    assert [row["email"] for row in results] == [staff.email]


def test_ordering_by_email(admin_api, manager, staff):
    emails = [r["email"] for r in admin_api.get(LIST_URL, {"ordering": "email"}).data["results"]]
    assert emails == sorted(emails)


def test_pagination_page_size_param(admin_api, manager, staff):
    response = admin_api.get(LIST_URL, {"page_size": 1})
    assert len(response.data["results"]) == 1
    assert response.data["next"] is not None


# ------------------------------------------------------------------ create


def test_create_with_password(admin_api):
    payload = {
        "email": "New@Example.com",
        "first_name": "Nina",
        "last_name": "Reyes",
        "role": "staff",
        "password": "V3ry!secure987",
    }
    response = admin_api.post(LIST_URL, payload)

    assert response.status_code == 201
    assert "password" not in response.data
    user = User.objects.get(pk=response.data["id"])
    assert user.email == "new@example.com"  # normalized to lowercase
    assert user.check_password("V3ry!secure987")
    assert len(mail.outbox) == 0  # password given -> no invite email


def test_create_without_password_sends_invite(admin_api):
    payload = {"email": "invitee@example.com", "first_name": "Ivy", "role": "manager"}
    response = admin_api.post(LIST_URL, payload)

    assert response.status_code == 201
    user = User.objects.get(pk=response.data["id"])
    assert not user.has_usable_password()  # cannot log in until invite used
    assert len(mail.outbox) == 1
    assert "invited" in mail.outbox[0].subject.lower()


def test_create_duplicate_email_case_insensitive(admin_api, staff):
    response = admin_api.post(LIST_URL, {"email": "STAFF@example.com", "role": "staff"})
    assert response.status_code == 400
    assert "email" in response.data


def test_create_weak_password_rejected(admin_api):
    response = admin_api.post(LIST_URL, {"email": "x@example.com", "password": "123"})
    assert response.status_code == 400
    assert "password" in response.data


def test_create_invalid_role_rejected(admin_api):
    response = admin_api.post(LIST_URL, {"email": "x@example.com", "role": "superhero"})
    assert response.status_code == 400
    assert "role" in response.data


# ------------------------------------------------------------------ update


def test_patch_updates_names_only(admin_api, staff):
    response = admin_api.patch(
        detail_url(staff.id), {"first_name": "Stanley", "role": "admin", "email": "h4x@evil.com"}
    )
    assert response.status_code == 200
    staff.refresh_from_db()
    assert staff.first_name == "Stanley"
    # role/email are not in the update serializer -> silently ignored
    assert staff.role == User.Role.STAFF
    assert staff.email == "staff@example.com"


def test_put_is_not_allowed(admin_api, staff):
    assert admin_api.put(detail_url(staff.id), {"first_name": "X"}).status_code == 405


# ------------------------------------------------------------ assign role


def test_assign_role(admin_api, staff):
    url = reverse("users:user-assign-role", args=[staff.id])
    response = admin_api.post(url, {"role": "manager"})
    assert response.status_code == 200
    staff.refresh_from_db()
    assert staff.role == User.Role.MANAGER


def test_assign_role_rejects_unknown_role(admin_api, staff):
    url = reverse("users:user-assign-role", args=[staff.id])
    assert admin_api.post(url, {"role": "root"}).status_code == 400


def test_cannot_change_own_role(admin_api, admin):
    url = reverse("users:user-assign-role", args=[admin.id])
    assert admin_api.post(url, {"role": "staff"}).status_code == 403
    admin.refresh_from_db()
    assert admin.role == User.Role.ADMIN


def test_last_admin_guard():
    """Unit-test the defense-in-depth guard (self-guard already covers the API path)."""
    from rest_framework.exceptions import ValidationError

    only_admin = User.objects.create_user(email="solo@example.com", role=User.Role.ADMIN)
    viewset = UserViewSet()
    with pytest.raises(ValidationError):
        viewset._guard_not_last_admin(only_admin, "demote")

    User.objects.create_user(email="second@example.com", role=User.Role.ADMIN)
    viewset._guard_not_last_admin(only_admin, "demote")  # no longer raises


# ------------------------------------------------- deactivate / activate


def test_deactivate_blocks_login_and_revokes_tokens(admin_api, api, staff):
    RefreshToken.for_user(staff)  # simulate an existing session
    response = admin_api.post(reverse("users:user-deactivate", args=[staff.id]))

    assert response.status_code == 200
    staff.refresh_from_db()
    assert staff.is_active is False
    outstanding = OutstandingToken.objects.filter(user=staff)
    assert BlacklistedToken.objects.filter(token__in=outstanding).count() == outstanding.count()

    fresh_client = APIClient()
    login = fresh_client.post(
        reverse("accounts:login"), {"email": staff.email, "password": PASSWORD}, format="json"
    )
    assert login.status_code == 401


def test_cannot_deactivate_self(admin_api, admin):
    response = admin_api.post(reverse("users:user-deactivate", args=[admin.id]))
    assert response.status_code == 403
    admin.refresh_from_db()
    assert admin.is_active is True


def test_activate(admin_api, staff):
    staff.is_active = False
    staff.save()
    response = admin_api.post(reverse("users:user-activate", args=[staff.id]))
    assert response.status_code == 200
    staff.refresh_from_db()
    assert staff.is_active is True


# ------------------------------------------------------------ soft delete


def test_delete_is_soft(admin_api, staff):
    response = admin_api.delete(detail_url(staff.id))
    assert response.status_code == 204

    staff.refresh_from_db()  # row still exists — that's the point
    assert staff.deleted_at is not None
    assert staff.is_active is False
    # invisible to the API from now on
    assert admin_api.get(detail_url(staff.id)).status_code == 404


def test_cannot_delete_self(admin_api, admin):
    assert admin_api.delete(detail_url(admin.id)).status_code == 403
    admin.refresh_from_db()
    assert admin.deleted_at is None


# ----------------------------------------------------------------- avatar


@pytest.fixture
def media_root(settings, tmp_path):
    """Uploads land in a throwaway dir, not the real media/ folder."""
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def avatar_url(user_id):
    return reverse("users:user-avatar", args=[user_id])


def test_admin_uploads_avatar(admin_api, staff, media_root):
    response = admin_api.put(avatar_url(staff.id), {"avatar": make_image()}, format="multipart")
    assert response.status_code == 200
    staff.refresh_from_db()
    assert staff.avatar  # stored
    assert "avatar" in response.data and response.data["avatar"]
    # stored under avatars/yyyy/mm/<uuid>.png — never the original name
    assert staff.avatar.name.startswith("avatars/")
    assert "avatar.png" not in staff.avatar.name


def test_replacing_avatar_deletes_old_file(admin_api, staff, media_root):
    admin_api.put(avatar_url(staff.id), {"avatar": make_image()}, format="multipart")
    staff.refresh_from_db()
    old_path = staff.avatar.path

    admin_api.put(avatar_url(staff.id), {"avatar": make_image()}, format="multipart")
    assert not os.path.exists(old_path)


def test_avatar_rejects_non_image(admin_api, staff, media_root):
    fake = SimpleUploadedFile("evil.png", b"not an image", content_type="image/png")
    response = admin_api.put(avatar_url(staff.id), {"avatar": fake}, format="multipart")
    assert response.status_code == 400


def test_avatar_rejects_disallowed_extension(admin_api, staff, media_root):
    gif = make_image(name="pic.gif", fmt="GIF")
    response = admin_api.put(avatar_url(staff.id), {"avatar": gif}, format="multipart")
    assert response.status_code == 400


def test_avatar_rejects_oversize(admin_api, staff, media_root):
    # Random noise doesn't compress — a 900×900 noise PNG is well over 2 MB.
    noise = Image.frombytes("RGB", (900, 900), os.urandom(900 * 900 * 3))
    buf = io.BytesIO()
    noise.save(buf, format="PNG")
    big = SimpleUploadedFile("big.png", buf.getvalue(), content_type="image/png")

    response = admin_api.put(avatar_url(staff.id), {"avatar": big}, format="multipart")
    assert response.status_code == 400


def test_delete_avatar(admin_api, staff, media_root):
    admin_api.put(avatar_url(staff.id), {"avatar": make_image()}, format="multipart")
    response = admin_api.delete(avatar_url(staff.id))
    assert response.status_code == 204
    staff.refresh_from_db()
    assert not staff.avatar


def test_user_manages_own_avatar_via_me(api, staff, media_root):
    api.force_authenticate(user=staff)
    url = reverse("accounts:me-avatar")

    response = api.put(url, {"avatar": make_image()}, format="multipart")
    assert response.status_code == 200
    staff.refresh_from_db()
    assert staff.avatar

    assert api.delete(url).status_code == 204


def test_me_avatar_requires_login(api):
    assert api.put(reverse("accounts:me-avatar"), {}, format="multipart").status_code == 401


# ------------------------------------------------------------- assignable


def test_manager_lists_assignable_users(api, manager, staff, admin):
    # The one users-endpoint managers MAY hit: the dropdown source for
    # pickers (client account manager). Slim shape, nothing admin-only.
    api.force_authenticate(user=manager)

    response = api.get(reverse("users:user-assignable"))

    assert response.status_code == 200
    assert {u["email"] for u in response.data} == {
        "admin@example.com",
        "manager@example.com",
        "staff@example.com",
    }
    assert set(response.data[0]) == {"id", "name", "email", "role"}


def test_staff_cannot_list_assignable_users(api, staff):
    api.force_authenticate(user=staff)
    assert api.get(reverse("users:user-assignable")).status_code == 403


def test_assignable_excludes_soft_deleted(admin_api, staff):
    from apps.accounts import services

    services.soft_delete_user(staff)

    response = admin_api.get(reverse("users:user-assignable"))
    assert response.status_code == 200
    assert staff.email not in {u["email"] for u in response.data}
