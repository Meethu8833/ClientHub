"""
Router-generated URLs for the user-management API.

Mounted at /api/v1/ in config/urls.py, so the resource lives at
/api/v1/users/. Separate from urls.py (mounted at /api/v1/auth/) because
auth and user administration are different modules with different audiences.
"""

from rest_framework.routers import DefaultRouter

from .views_users import UserViewSet

app_name = "users"

router = DefaultRouter()
# basename -> URL names: users:user-list, users:user-detail, users:user-deactivate…
router.register("users", UserViewSet, basename="user")

urlpatterns = router.urls
