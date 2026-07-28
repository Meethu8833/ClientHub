import uuid
from decimal import Decimal

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


def avatar_upload_path(instance, filename):
    """
    Storage path for profile pictures: avatars/<yyyy>/<mm>/<uuid>.<ext>.

    The stored name is a random UUID — never the user's original filename.
    Original names can collide, contain path tricks ("../../etc/passwd") or
    characters the filesystem dislikes; a UUID kills all three problems.
    """
    ext = filename.rsplit(".", 1)[-1].lower()
    now = timezone.now()
    return f"avatars/{now:%Y/%m}/{uuid.uuid4().hex}.{ext}"


class UserManager(BaseUserManager):
    """
    Custom manager needed because we removed `username`: the default manager's
    create_user/create_superuser expect a username argument.
    """

    use_in_migrations = True

    def alive(self):
        """
        Everyone except soft-deleted users — what the API should query.

        Deliberately a method, NOT a filtered default manager: Django's auth
        machinery (login, admin, FK validation) uses the default manager, and
        hiding rows from it causes confusing "user does not exist" bugs.
        """
        return self.filter(deleted_at__isnull=True)

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("The email address is required.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)  # hashes — never stores the raw password
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    ClientHub user. Email is the login identifier (no username), plus an
    application `role` that drives the permission matrix in ARCHITECTURE.md §8.
    """

    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        MANAGER = "manager", "Manager"
        STAFF = "staff", "Staff"

    username = None  # removes the inherited column entirely
    email = models.EmailField("email address", unique=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STAFF)
    # Flipped by the email-verification flow. Distinct from is_active:
    # is_active=False blocks login entirely; this only records verification.
    is_email_verified = models.BooleanField(default=False)
    avatar = models.ImageField(upload_to=avatar_upload_path, blank=True, null=True)
    # Soft delete (ARCHITECTURE.md §4): a "deleted" user keeps their row so
    # history (clients they managed, tasks, time entries) stays intact.
    # NULL = alive; a timestamp = when they were deleted. Deleted users are
    # excluded from API querysets and can never log in (is_active is also
    # set False on delete). Deactivation is the SEPARATE, reversible state
    # where deleted_at stays NULL and only is_active is False.
    deleted_at = models.DateTimeField(null=True, blank=True)
    # Contracted working hours per week — the basis of capacity planning
    # (teams app). A property of the EMPLOYEE, not of any team: part-timers
    # bring a smaller week to every team they join. Decimal, not int —
    # real contracts land on halves (37.5, 20.0).
    weekly_capacity_hours = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        default=Decimal("40.0"),
        validators=[MinValueValidator(0), MaxValueValidator(80)],
    )

    USERNAME_FIELD = "email"  # what Django asks for at login
    REQUIRED_FIELDS = []  # extra prompts for createsuperuser (email+password only)

    objects = UserManager()

    def __str__(self):
        return self.email
