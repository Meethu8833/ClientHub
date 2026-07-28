"""
Delete the physical file when its DocumentVersion row is deleted (§9).

Django does NOT do this automatically (since 1.3): deleting a model row
leaves the file on disk/bucket forever. post_delete fires after the row is
gone — if the transaction rolls back the delete, the signal never ran, so we
never destroy a file whose row survived.

Deleting a Document CASCADEs into its versions, and Django's cascade goes
through the ORM collector, which fires post_delete once per version — so one
DELETE /documents/{id}/ cleans up every historical file.
"""

from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import DocumentVersion


@receiver(post_delete, sender=DocumentVersion)
def delete_file_on_version_delete(sender, instance, **kwargs):
    if instance.file:
        # save=False: the row no longer exists — nothing to update.
        instance.file.delete(save=False)
