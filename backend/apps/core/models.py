from django.db import models


class TimeStampedModel(models.Model):
    """
    Abstract base every business model inherits: automatic created/updated
    timestamps. abstract = True means Django creates NO table for this class —
    the two columns are copied into each child model's table instead.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
