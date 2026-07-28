"""
Document API tests: the three upload gates (size, extension, content sniff),
target validation, scoped listing, permission-checked download, delete rules,
and file cleanup on delete.
"""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.clients.models import Client
from apps.documents import serializers as doc_serializers
from apps.documents.models import Document

PASSWORD = "Str0ng!pass123"

pytestmark = pytest.mark.django_db

LIST_URL = reverse("documents:document-list")

# A tiny but REAL pdf header — libmagic identifies this as application/pdf.
PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< >>\n%%EOF\n"


def make_pdf(name="proposal.pdf"):
    return SimpleUploadedFile(name, PDF_BYTES, content_type="application/pdf")


def make_png(name="logo.png"):
    buf = io.BytesIO()
    Image.new("RGB", (5, 5), color=(0, 120, 255)).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


@pytest.fixture(autouse=True)
def _tmp_media(settings, tmp_path):
    """Uploads land in a throwaway dir, not the real media/ folder."""
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def manager():
    return User.objects.create_user(
        email="manager@example.com", password=PASSWORD, role=User.Role.MANAGER
    )


@pytest.fixture
def staff():
    return User.objects.create_user(
        email="staff@example.com", password=PASSWORD, role=User.Role.STAFF
    )


@pytest.fixture
def manager_api(manager):
    c = APIClient()
    c.force_authenticate(user=manager)
    return c


@pytest.fixture
def staff_api(staff):
    c = APIClient()
    c.force_authenticate(user=staff)
    return c


@pytest.fixture
def acme():
    return Client.objects.create(name="Acme Fintech")


def upload(api, client_id, file=None):
    return api.post(
        LIST_URL,
        {"file": file or make_pdf(), "content_type": "client", "object_id": client_id},
        format="multipart",
    )


# ------------------------------------------------------------------ upload


def test_upload_pdf_to_client(manager_api, manager, acme):
    res = upload(manager_api, acme.id)
    assert res.status_code == 201
    assert res.data["original_name"] == "proposal.pdf"
    assert res.data["mime_type"] == "application/pdf"
    assert res.data["size_bytes"] == len(PDF_BYTES)
    assert res.data["uploaded_by"]["id"] == manager.id
    assert res.data["target"] == {"content_type": "client", "object_id": acme.id}
    assert res.data["version"] == 1
    assert res.data["versions_count"] == 1
    doc = Document.objects.get(pk=res.data["id"])
    assert doc.content_object == acme
    assert doc.current_version.version_number == 1
    # Stored under a UUID name, never the original (path-traversal safety).
    assert "proposal" not in doc.current_version.file.name


def test_staff_may_upload_too(staff_api, acme):
    assert upload(staff_api, acme.id).status_code == 201


def test_disallowed_extension_rejected(manager_api, acme):
    exe = SimpleUploadedFile("malware.exe", b"MZ\x90\x00", content_type="application/exe")
    res = upload(manager_api, acme.id, file=exe)
    assert res.status_code == 400
    assert "file" in res.data


def test_content_must_match_extension(manager_api, acme):
    disguised = SimpleUploadedFile("innocent.png", PDF_BYTES, content_type="image/png")
    res = upload(manager_api, acme.id, file=disguised)
    assert res.status_code == 400
    assert "does not match" in str(res.data["file"][0])


def test_oversize_rejected(manager_api, acme, monkeypatch):
    monkeypatch.setattr(doc_serializers, "MAX_UPLOAD_BYTES", 10)
    res = upload(manager_api, acme.id)
    assert res.status_code == 400
    assert "too large" in str(res.data["file"][0]).lower()


def test_upload_to_missing_or_deleted_client_rejected(manager_api, acme):
    assert upload(manager_api, 99999).status_code == 400
    acme.is_active = False
    acme.save()
    assert upload(manager_api, acme.id).status_code == 400


# -------------------------------------------------------------------- list


def test_list_requires_target_params(manager_api):
    assert manager_api.get(LIST_URL).status_code == 400


def test_list_returns_only_that_objects_documents(manager_api, acme):
    other = Client.objects.create(name="Other Co")
    upload(manager_api, acme.id)
    upload(manager_api, other.id, file=make_png())
    res = manager_api.get(LIST_URL, {"content_type": "client", "object_id": acme.id})
    assert res.status_code == 200
    assert res.data["count"] == 1
    assert res.data["results"][0]["original_name"] == "proposal.pdf"


# ---------------------------------------------------------------- download


def test_download_streams_the_bytes(manager_api, acme):
    doc_id = upload(manager_api, acme.id).data["id"]
    res = manager_api.get(reverse("documents:document-download", args=[doc_id]))
    assert res.status_code == 200
    assert b"".join(res.streaming_content) == PDF_BYTES
    assert 'filename="proposal.pdf"' in res["Content-Disposition"]


def test_download_requires_auth(manager_api, acme):
    doc_id = upload(manager_api, acme.id).data["id"]
    res = APIClient().get(reverse("documents:document-download", args=[doc_id]))
    assert res.status_code == 401


# ------------------------------------------------------------------ delete


def test_staff_deletes_own_but_not_others(manager_api, staff_api, acme):
    own = upload(staff_api, acme.id).data["id"]
    others = upload(manager_api, acme.id).data["id"]
    assert staff_api.delete(reverse("documents:document-detail", args=[others])).status_code == 403
    assert staff_api.delete(reverse("documents:document-detail", args=[own])).status_code == 204


def test_manager_deletes_any_and_file_is_removed(manager_api, staff_api, acme):
    doc_id = upload(staff_api, acme.id).data["id"]
    doc = Document.objects.get(pk=doc_id)
    storage, name = doc.current_version.file.storage, doc.current_version.file.name
    assert storage.exists(name)
    assert (
        manager_api.delete(reverse("documents:document-detail", args=[doc_id])).status_code == 204
    )
    assert not storage.exists(name)  # post_delete signal cleaned the disk


# -------------------------------------------------------------- versioning


def versions_url(doc_id):
    return reverse("documents:document-versions", args=[doc_id])


def test_new_version_promotes_current(staff_api, acme):
    doc_id = upload(staff_api, acme.id).data["id"]
    res = staff_api.post(versions_url(doc_id), {"file": make_png()}, format="multipart")
    assert res.status_code == 201
    assert res.data["version_number"] == 2
    assert res.data["mime_type"] == "image/png"
    doc = Document.objects.get(pk=doc_id)
    assert doc.current_version.version_number == 2
    # The document read shape now reflects the new current version.
    detail = staff_api.get(reverse("documents:document-detail", args=[doc_id])).data
    assert detail["version"] == 2
    assert detail["versions_count"] == 2
    assert detail["mime_type"] == "image/png"


def test_version_history_newest_first(staff_api, acme):
    doc_id = upload(staff_api, acme.id).data["id"]
    staff_api.post(versions_url(doc_id), {"file": make_png()}, format="multipart")
    res = staff_api.get(versions_url(doc_id))
    assert res.status_code == 200
    assert [v["version_number"] for v in res.data] == [2, 1]
    assert "?version=1" in res.data[1]["download_url"]


def test_staff_cannot_version_others_document(manager_api, staff_api, acme):
    managers_doc = upload(manager_api, acme.id).data["id"]
    staffs_doc = upload(staff_api, acme.id).data["id"]
    res = staff_api.post(versions_url(managers_doc), {"file": make_png()}, format="multipart")
    assert res.status_code == 403
    # …but managers may re-version anyone's document.
    res = manager_api.post(versions_url(staffs_doc), {"file": make_png()}, format="multipart")
    assert res.status_code == 201


def test_version_upload_runs_the_same_gates(staff_api, acme):
    doc_id = upload(staff_api, acme.id).data["id"]
    exe = SimpleUploadedFile("malware.exe", b"MZ\x90\x00", content_type="application/exe")
    res = staff_api.post(versions_url(doc_id), {"file": exe}, format="multipart")
    assert res.status_code == 400
    assert "file" in res.data


def test_download_specific_version(staff_api, acme):
    doc_id = upload(staff_api, acme.id).data["id"]
    staff_api.post(versions_url(doc_id), {"file": make_png()}, format="multipart")
    url = reverse("documents:document-download", args=[doc_id])
    # Default: the current (png) version; ?version=1 reaches the original pdf.
    assert staff_api.get(url).headers["Content-Type"] == "image/png"
    old = staff_api.get(url, {"version": 1})
    assert b"".join(old.streaming_content) == PDF_BYTES
    assert staff_api.get(url, {"version": 9}).status_code == 404
    assert staff_api.get(url, {"version": "abc"}).status_code == 400


def test_delete_document_removes_all_version_files(manager_api, acme):
    doc_id = upload(manager_api, acme.id).data["id"]
    manager_api.post(versions_url(doc_id), {"file": make_png()}, format="multipart")
    doc = Document.objects.get(pk=doc_id)
    files = [(v.file.storage, v.file.name) for v in doc.versions.all()]
    assert len(files) == 2 and all(s.exists(n) for s, n in files)
    manager_api.delete(reverse("documents:document-detail", args=[doc_id]))
    assert not any(s.exists(n) for s, n in files)  # cascade fired both signals


# ------------------------------------------------------------ orphan sweep


def orphan_file():
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage

    return default_storage.save("documents/2020/01/orphan.pdf", ContentFile(PDF_BYTES))


def test_sweep_deletes_orphans_keeps_referenced(manager_api, acme):
    from django.core.files.storage import default_storage
    from django.core.management import call_command

    doc = Document.objects.get(pk=upload(manager_api, acme.id).data["id"])
    referenced = doc.current_version.file.name
    orphan = orphan_file()
    call_command("sweep_orphan_files", min_age_hours=0)
    assert default_storage.exists(referenced)
    assert not default_storage.exists(orphan)


def test_sweep_dry_run_and_age_guard(manager_api, acme):
    from django.core.files.storage import default_storage
    from django.core.management import call_command

    orphan = orphan_file()
    call_command("sweep_orphan_files", "--dry-run", min_age_hours=0)
    assert default_storage.exists(orphan)  # dry-run never deletes
    call_command("sweep_orphan_files")  # default 24h guard: file too new
    assert default_storage.exists(orphan)
