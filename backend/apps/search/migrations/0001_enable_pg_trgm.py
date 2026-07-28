"""
Enable the `pg_trgm` Postgres extension.

pg_trgm ("trigram") splits text into overlapping 3-character chunks
("acme" → "  a", " ac", "acm", "cme", "me ") and lets a GIN index answer
`ILIKE '%term%'` — a query a normal B-tree index can NOT accelerate,
because B-trees only help when the *start* of the value is known.

This lives in the model-less `search` app so every trigram index migration
in other apps can declare a dependency on it (extensions must exist BEFORE
an index that uses their operator class is created). CREATE EXTENSION needs
a superuser — the default Docker postgres user is one; on managed Postgres
(RDS etc.) pg_trgm is on the allow-list and works the same way.
"""

from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [TrigramExtension()]
