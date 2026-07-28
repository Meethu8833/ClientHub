"""
Routes for the clients app, mounted at /api/v1/ in config/urls.py:

    /api/v1/clients/    full resource (+ nested /clients/{id}/contacts/)
    /api/v1/contacts/   detail/update/delete only (flat writes, §6)
"""

from rest_framework.routers import DefaultRouter

from .views import ClientViewSet, ContactViewSet

app_name = "clients"

router = DefaultRouter()
# URL names: clients:client-list, clients:client-detail, clients:client-contacts
router.register("clients", ClientViewSet, basename="client")
# Only detail routes exist (the viewset has no list/create actions).
router.register("contacts", ContactViewSet, basename="contact")

urlpatterns = router.urls
