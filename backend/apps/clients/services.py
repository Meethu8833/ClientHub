"""
Side-effectful business logic for the clients app (ARCHITECTURE.md §11:
views stay thin; multi-row writes live in service functions inside
transaction.atomic()).
"""

from django.db import transaction
from django.utils import timezone

from .models import Client, Contact


def soft_delete_client(client: Client) -> None:
    """
    "Delete" = hide from the API, keep the row (projects, invoices and
    documents keep pointing at it for audit). updated_at records when.
    """
    client.is_active = False
    client.save(update_fields=["is_active", "updated_at"])


@transaction.atomic
def save_contact(contact: Contact) -> Contact:
    """
    Save a contact, keeping the one-primary-per-client invariant.

    If this contact is becoming primary, demote the current primary first —
    inside one transaction, so a crash between the two writes can't leave the
    client with zero primaries, and the DB constraint can't reject us for
    briefly having two.
    """
    if contact.is_primary:
        Contact.objects.filter(client=contact.client, is_primary=True).exclude(
            pk=contact.pk
        ).update(is_primary=False, updated_at=timezone.now())
    contact.save()
    return contact
