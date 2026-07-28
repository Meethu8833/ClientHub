"""
Serializers for the teams app (§6 conventions — read/write split):

- Department: List (table row + counts) / Detail (+teams) / Write
- Team:       List (row + member_count, total_allocation) / Detail (+seats) / Write
- TeamMembership: read shape + Create (nested under team) + Update (allocation only)
- TimeOff:    read shape + Write (staff restricted to themselves)

The two invariants that span rows — a person's allocations summing ≤ 100 %,
and absence windows never overlapping — live HERE, not in the DB: a CHECK
constraint sees one row at a time, so cross-row rules belong to the
application layer (with the per-row DB constraints as backstops).
"""

from django.contrib.auth import get_user_model
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from . import services
from .models import Department, Team, TeamMembership, TimeOff

User = get_user_model()


# OpenAPI components are keyed by class name; projects has its own
# UserMiniSerializer, so this one needs an explicit distinct component name
# or the generated schema silently merges the two.
@extend_schema_serializer(component_name="TeamsUserMini")
class UserMiniSerializer(serializers.ModelSerializer):
    """Mini user embedded in reads: {id, name, email}."""

    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "name", "email"]

    def get_name(self, obj):
        return obj.get_full_name() or obj.email


class DepartmentMiniSerializer(serializers.ModelSerializer):
    """Link chip for rows that hang off a department."""

    class Meta:
        model = Department
        fields = ["id", "name"]


class TeamMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ["id", "name"]


# ---------------------------------------------------------------- department


class DepartmentListSerializer(serializers.ModelSerializer):
    """One table row. team_count / member_count are viewset annotations (SQL)."""

    head = UserMiniSerializer(read_only=True)
    team_count = serializers.IntegerField(read_only=True)
    member_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Department
        fields = ["id", "name", "head", "team_count", "member_count", "created_at"]


class DepartmentDetailSerializer(serializers.ModelSerializer):
    """Full record for the department page: description + its live teams."""

    head = UserMiniSerializer(read_only=True)
    teams = TeamMiniSerializer(many=True, read_only=True)
    team_count = serializers.IntegerField(read_only=True)
    member_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Department
        fields = [
            "id",
            "name",
            "description",
            "head",
            "teams",
            "team_count",
            "member_count",
            "created_at",
            "updated_at",
        ]


class DepartmentWriteSerializer(serializers.ModelSerializer):
    """POST/PATCH body. Reads embed the head; writes accept head_id (§6)."""

    head_id = serializers.PrimaryKeyRelatedField(
        source="head", queryset=User.objects.none(), required=False, allow_null=True
    )

    class Meta:
        model = Department
        fields = ["name", "description", "head_id"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Soft-deleted users can't head a department; evaluated per request.
        self.fields["head_id"].queryset = User.objects.alive()

    def validate_name(self, value):
        # Friendly 400 before the conditional unique constraint 500s.
        if (
            Department.objects.exclude(pk=getattr(self.instance, "pk", None))
            .filter(name__iexact=value, is_active=True)
            .exists()
        ):
            raise serializers.ValidationError("A department with this name already exists.")
        return value


# ---------------------------------------------------------------------- team


class TeamMembershipSerializer(serializers.ModelSerializer):
    """Read shape for one seat. created_at doubles as 'joined' date."""

    user = UserMiniSerializer(read_only=True)
    team = TeamMiniSerializer(read_only=True)

    class Meta:
        model = TeamMembership
        fields = ["id", "team", "user", "allocation_percent", "created_at"]
        read_only_fields = fields


class TeamListSerializer(serializers.ModelSerializer):
    """One table row. member_count / total_allocation are annotations."""

    department = DepartmentMiniSerializer(read_only=True)
    lead = UserMiniSerializer(read_only=True)
    member_count = serializers.IntegerField(read_only=True)
    total_allocation = serializers.IntegerField(read_only=True)

    class Meta:
        model = Team
        fields = [
            "id",
            "name",
            "department",
            "lead",
            "member_count",
            "total_allocation",
            "created_at",
        ]


class TeamDetailSerializer(serializers.ModelSerializer):
    """Full record for the team page: every seat with its allocation."""

    department = DepartmentMiniSerializer(read_only=True)
    lead = UserMiniSerializer(read_only=True)
    members = TeamMembershipSerializer(source="memberships", many=True, read_only=True)
    member_count = serializers.IntegerField(read_only=True)
    total_allocation = serializers.IntegerField(read_only=True)

    class Meta:
        model = Team
        fields = [
            "id",
            "name",
            "description",
            "department",
            "lead",
            "members",
            "member_count",
            "total_allocation",
            "created_at",
            "updated_at",
        ]


class TeamWriteSerializer(serializers.ModelSerializer):
    """
    POST /departments/{id}/teams/ and PATCH /teams/{id}/ body. `department`
    comes from the URL on create (context) and is immutable after — same rule
    as "a project cannot be moved to another client"; reorganisations are a
    disband + recreate, which keeps history honest.
    """

    lead_id = serializers.PrimaryKeyRelatedField(
        source="lead", queryset=User.objects.none(), required=False, allow_null=True
    )

    class Meta:
        model = Team
        fields = ["name", "description", "lead_id"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lead_id"].queryset = User.objects.alive()

    def _department(self):
        return self.context.get("department") or self.instance.department

    def validate_name(self, value):
        if (
            Team.objects.exclude(pk=getattr(self.instance, "pk", None))
            .filter(department=self._department(), name__iexact=value, is_active=True)
            .exists()
        ):
            raise serializers.ValidationError("This department already has a team with this name.")
        return value

    def create(self, validated_data):
        return Team.objects.create(department=self.context["department"], **validated_data)


# ----------------------------------------------------------------- membership


class TeamMembershipCreateSerializer(serializers.Serializer):
    """POST /teams/{id}/members/ body: {user_id, allocation_percent}."""

    user_id = serializers.PrimaryKeyRelatedField(source="user", queryset=User.objects.none())
    allocation_percent = serializers.IntegerField(min_value=1, max_value=100, default=100)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user_id"].queryset = User.objects.alive()

    def validate(self, attrs):
        team = self.context["team"]
        user = attrs["user"]
        if team.memberships.filter(user=user).exists():
            raise serializers.ValidationError(
                {"user_id": "This user is already a member of the team."}
            )
        # THE allocation invariant: all seats of one person sum to ≤ 100 %.
        available = 100 - services.user_total_allocation(user)
        if attrs["allocation_percent"] > available:
            raise serializers.ValidationError(
                {
                    "allocation_percent": (
                        f"Over-allocation: this user has only {available}% of their "
                        "week left across active teams."
                    )
                }
            )
        return attrs

    def create(self, validated_data):
        return TeamMembership.objects.create(team=self.context["team"], **validated_data)


class TeamMembershipUpdateSerializer(serializers.Serializer):
    """PATCH /team-memberships/{id}/ may change the allocation, nothing else —
    moving a person to another team is remove + add (two auditable events)."""

    allocation_percent = serializers.IntegerField(min_value=1, max_value=100)

    def validate_allocation_percent(self, value):
        membership = self.instance
        # exclude=self: raising 60 → 80 must not count the old 60 against you.
        available = 100 - services.user_total_allocation(membership.user, exclude=membership)
        if value > available:
            raise serializers.ValidationError(
                f"Over-allocation: this user has only {available}% of their week "
                "left across active teams."
            )
        return value

    def update(self, instance, validated_data):
        instance.allocation_percent = validated_data["allocation_percent"]
        instance.save(update_fields=["allocation_percent", "updated_at"])
        return instance


# ------------------------------------------------------------------ time off


class TimeOffSerializer(serializers.ModelSerializer):
    """Read shape. workdays = the weekdays the absence actually costs."""

    user = UserMiniSerializer(read_only=True)
    workdays = serializers.SerializerMethodField()

    class Meta:
        model = TimeOff
        fields = [
            "id",
            "user",
            "type",
            "start_date",
            "end_date",
            "workdays",
            "reason",
            "created_at",
        ]
        read_only_fields = fields

    def get_workdays(self, obj):
        return services.workdays_between(obj.start_date, obj.end_date)


class TimeOffWriteSerializer(serializers.ModelSerializer):
    """
    POST /time-off/ and PATCH /time-off/{id}/ body. user_id is optional and
    defaults to the caller; STAFF may only record their OWN absences —
    letting anyone book a colleague "on vacation" would be a griefing vector
    (their capacity silently drops to zero).
    """

    user_id = serializers.PrimaryKeyRelatedField(
        source="user", queryset=User.objects.none(), required=False
    )

    class Meta:
        model = TimeOff
        fields = ["user_id", "type", "start_date", "end_date", "reason"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["user_id"].queryset = User.objects.alive()

    def validate(self, attrs):
        request = self.context["request"]

        def get(field):
            # PATCH sends only changed fields — read "new if sent, else current".
            return attrs.get(field, getattr(self.instance, field, None))

        user = get("user") or request.user
        if request.user.role == User.Role.STAFF and user != request.user:
            raise serializers.ValidationError({"user_id": "You may only record your own time off."})
        attrs["user"] = user

        start, end = get("start_date"), get("end_date")
        if end < start:
            raise serializers.ValidationError(
                {"end_date": "End date cannot be before the start date."}
            )

        # No double-booking: overlapping rows would double-count absence days
        # in every capacity report. Same overlap predicate as the report query.
        if (
            TimeOff.objects.exclude(pk=getattr(self.instance, "pk", None))
            .filter(user=user, start_date__lte=end, end_date__gte=start)
            .exists()
        ):
            raise serializers.ValidationError(
                {"start_date": "This period overlaps an existing time-off entry."}
            )
        return attrs
