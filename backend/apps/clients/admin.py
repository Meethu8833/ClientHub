from django.contrib import admin

from .models import Client, Contact


class ContactInline(admin.TabularInline):
    model = Contact
    extra = 0


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ["name", "status", "city", "gst_number", "account_manager", "is_active"]
    list_filter = ["status", "is_active"]
    search_fields = ["name", "email", "gst_number"]
    inlines = [ContactInline]


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ["name", "client", "position", "email", "is_primary"]
    search_fields = ["name", "email", "client__name"]
