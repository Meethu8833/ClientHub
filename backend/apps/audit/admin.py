from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """
    Viewer only. Add/change/delete are switched off so even a superuser
    cannot rewrite history through the admin — an audit trail you can edit
    is not an audit trail (same rule as Activity).
    """

    list_display = ("created_at", "action", "actor_repr", "target_repr", "ip_address")
    list_filter = ("action",)
    search_fields = ("actor_repr", "target_repr")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
