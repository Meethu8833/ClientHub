"""
Routes for the teams app, mounted at /api/v1/ in config/urls.py:

    /api/v1/departments/        full resource (+ nested teams)
    /api/v1/teams/              flat list/detail/update/delete
                                (+ nested members, capacity report)
    /api/v1/team-memberships/   flat seat writes + allocation lookup
    /api/v1/time-off/           availability ledger CRUD
"""

from rest_framework.routers import DefaultRouter

from .views import DepartmentViewSet, TeamMembershipViewSet, TeamViewSet, TimeOffViewSet

app_name = "teams"

router = DefaultRouter()
# URL names: teams:department-list, teams:team-capacity, teams:time-off-detail…
router.register("departments", DepartmentViewSet, basename="department")
router.register("teams", TeamViewSet, basename="team")
router.register("team-memberships", TeamMembershipViewSet, basename="team-membership")
router.register("time-off", TimeOffViewSet, basename="time-off")

urlpatterns = router.urls
