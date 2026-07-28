"""
Data migration: seed one SlaPolicy row per priority with sane defaults.

A DATA migration (RunPython) instead of a fixture or manual insert because it
runs exactly once, everywhere — every dev machine, CI database and the prod
deploy get the same four rows without anyone remembering a manual step.
Admins tune the numbers later via PATCH /sla-policies/.
"""

from django.db import migrations

DEFAULTS = [
    # (priority, first_response_minutes, resolution_minutes)
    ("urgent", 30, 4 * 60),  # respond in 30 min, resolve within 4 h
    ("high", 60, 8 * 60),
    ("medium", 4 * 60, 24 * 60),
    ("low", 8 * 60, 3 * 24 * 60),
]


def seed(apps, schema_editor):
    # Always the HISTORICAL model via apps.get_model — importing the real
    # class would break once the model gains fields this migration predates.
    SlaPolicy = apps.get_model("tickets", "SlaPolicy")
    for priority, first, resolution in DEFAULTS:
        SlaPolicy.objects.get_or_create(
            priority=priority,
            defaults={"first_response_minutes": first, "resolution_minutes": resolution},
        )


def unseed(apps, schema_editor):
    apps.get_model("tickets", "SlaPolicy").objects.filter(
        priority__in=[p for p, *_ in DEFAULTS]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("tickets", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
