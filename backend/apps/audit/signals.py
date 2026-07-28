"""
Automatic model auditing via signals.

Why signals and not code in every view: the audit trail must be IMPOSSIBLE to
forget. A model listed in settings.AUDITED_MODELS is logged no matter which
view, service, admin page, or shell command saves it. The trade-offs:

- pre_save re-reads the old row (one extra query per audited save) — that is
  the price of a before/after diff, and audited models are low-volume
  business records, not hot paths.
- queryset.update() / bulk_create() / raw SQL BYPASS signals entirely —
  Django never loads the instances, so no signal fires. House rule: audited
  models are modified through instance.save(), never queryset.update().
- Many-to-many changes are not covered here; the Activity timeline already
  records those as business events (member_added etc.).
"""

from django.conf import settings
from django.contrib.auth.signals import user_login_failed
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from . import services
from .models import AuditLog

# Never diff/store these: password is a secret even hashed; last_login churns
# on every login; the timestamps are machine noise, not user intent.
DEFAULT_EXCLUDED_FIELDS = {"password", "last_login", "created_at", "updated_at"}


def _excluded_fields():
    return set(getattr(settings, "AUDIT_EXCLUDED_FIELDS", DEFAULT_EXCLUDED_FIELDS))


def _snapshot(instance):
    """
    {attname: json-safe value} for every concrete column.

    attname, not name: for a ForeignKey, name is "owner" (reading it queries
    the DB for the related object) while attname is "owner_id" (the raw
    column, already in memory). Non-primitive values (datetime, Decimal,
    FieldFile) are stringified so the diff always fits in a JSONField.
    """
    excluded = _excluded_fields()
    data = {}
    for field in instance._meta.concrete_fields:
        if field.name in excluded:
            continue
        value = getattr(instance, field.attname)
        if not isinstance(value, (str, int, float, bool, type(None))):
            value = str(value)
        data[field.attname] = value
    return data


def _classify(diff):
    """
    Soft delete looks like a plain update at the SQL level — recognise the
    two house conventions (Client.is_active flip, User.deleted_at stamp) and
    give the event its real name.
    """
    flag = diff.get("is_active")
    if flag is not None and flag["from"] is True and flag["to"] is False:
        return AuditLog.Action.SOFT_DELETED
    if flag is not None and flag["from"] is False and flag["to"] is True:
        return AuditLog.Action.RESTORED

    stamp = diff.get("deleted_at")
    if stamp is not None and stamp["from"] is None and stamp["to"] is not None:
        return AuditLog.Action.SOFT_DELETED
    if stamp is not None and stamp["from"] is not None and stamp["to"] is None:
        return AuditLog.Action.RESTORED

    return AuditLog.Action.UPDATED


def _stash_old(sender, instance, raw=False, **kwargs):
    """
    pre_save: fetch the current DB state and park it on the instance so
    post_save can diff against it. _base_manager, not objects: custom
    managers (like User's) may hide soft-deleted rows, and the audit must
    see everything.
    """
    if raw:  # loaddata fixtures — not user activity
        return
    if instance.pk is None:
        instance._audit_old = None
        return
    old = sender._base_manager.filter(pk=instance.pk).first()
    instance._audit_old = _snapshot(old) if old else None


def _log_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    if created:
        services.log(action=AuditLog.Action.CREATED, target=instance)
        return

    old = getattr(instance, "_audit_old", None)
    if old is None:
        return
    new = _snapshot(instance)
    diff = {
        key: {"from": old.get(key), "to": value}
        for key, value in new.items()
        if old.get(key) != value
    }
    if not diff:  # e.g. save() that only touched excluded fields
        return
    services.log(action=_classify(diff), target=instance, changes=diff)


def _log_delete(sender, instance, **kwargs):
    # Hard delete: the row is gone, so the final snapshot in `changes` is the
    # only record of what was destroyed.
    services.log(
        action=AuditLog.Action.DELETED, target=instance, changes=_snapshot(instance)
    )


def connect_model_signals():
    """
    Called from AuditConfig.ready(). Config over code: which models are
    audited is a settings list, so adding one is a one-line change and the
    full roster is readable in one place. dispatch_uid makes connecting
    idempotent (dev autoreload runs ready() twice).
    """
    from django.apps import apps as django_apps

    for label in getattr(settings, "AUDITED_MODELS", []):
        model = django_apps.get_model(label)
        pre_save.connect(_stash_old, sender=model, dispatch_uid=f"audit.pre.{label}")
        post_save.connect(_log_save, sender=model, dispatch_uid=f"audit.save.{label}")
        post_delete.connect(_log_delete, sender=model, dispatch_uid=f"audit.del.{label}")


@receiver(user_login_failed, dispatch_uid="audit.login_failed")
def _log_login_failed(sender, credentials, request=None, **kwargs):
    """
    Fired by django.contrib.auth.authenticate() on bad credentials — which
    SimpleJWT calls under the hood, so JWT logins are covered for free.
    Django masks the password before emitting the signal; we store only the
    attempted email (the signal successful logins DON'T get is user_logged_in
    — SimpleJWT never calls auth.login(), so success is logged in
    LoginSerializer instead).
    """
    email = credentials.get("email") or credentials.get("username") or ""
    services.log(
        action=AuditLog.Action.LOGIN_FAILED,
        changes={"email": email},
        request=request,
    )
