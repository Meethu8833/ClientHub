"""
Routes for the projects app, mounted at /api/v1/ in config/urls.py:

    /api/v1/projects/              full resource (+ nested members/milestones/tasks)
    /api/v1/project-memberships/   flat team-row writes (manager/admin)
    /api/v1/milestones/            flat list/detail/update/delete
    /api/v1/sprints/               flat detail/update/delete (+ start/complete/burndown)
    /api/v1/tasks/                 flat list/detail/update/delete (+ nested time-entries)
    /api/v1/time-entries/          flat report list + row fixes
    /api/v1/technologies/          tag list/create
"""

from rest_framework.routers import DefaultRouter

from .views import (
    MilestoneViewSet,
    ProjectMembershipViewSet,
    ProjectViewSet,
    SprintViewSet,
    TaskViewSet,
    TechnologyViewSet,
    TimeEntryViewSet,
)

app_name = "projects"

router = DefaultRouter()
# URL names: projects:project-list, projects:task-detail, projects:task-time-entries…
router.register("projects", ProjectViewSet, basename="project")
router.register("project-memberships", ProjectMembershipViewSet, basename="membership")
router.register("milestones", MilestoneViewSet, basename="milestone")
router.register("sprints", SprintViewSet, basename="sprint")
router.register("tasks", TaskViewSet, basename="task")
router.register("time-entries", TimeEntryViewSet, basename="time-entry")
router.register("technologies", TechnologyViewSet, basename="technology")

urlpatterns = router.urls
