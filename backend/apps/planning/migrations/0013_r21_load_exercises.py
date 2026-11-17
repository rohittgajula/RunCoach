"""Load the 708 exercises that the library is.

The library shipped empty. The table and the pictures both reached production
— the migration created one and the frontend image carried the other — and the
rows did not, because the rows only ever existed in a developer's database
after running `manage.py import_exercises` by hand. The screen came up saying
"0 exercises" with every filter reading zero, which is exactly what it should
say about an empty table and tells you nothing about why.

So the data ships as a migration. It is static reference data — 708 rows that
change when the upstream dataset does and not otherwise — and migrations are
the one thing that is guaranteed to run wherever this app is deployed, before
the backend starts serving. `import_exercises` is still there for refreshing
from upstream; this is what makes a deploy self-sufficient.

Reversible, and idempotent on slug, so re-running or rolling back is safe.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.db import migrations

DATA = Path(__file__).resolve().parent.parent / "data_exercises.json"


def load(apps, schema_editor):
    Exercise = apps.get_model("planning", "Exercise")
    rows = json.loads(DATA.read_text())
    # bulk_create with update_conflicts so a re-run updates rather than
    # colliding: the alternative is 708 round trips to ask what is already
    # there, for a table that is empty every time this matters.
    Exercise.objects.bulk_create(
        [Exercise(**row) for row in rows],
        update_conflicts=True,
        update_fields=[f for f in rows[0] if f != "slug"],
        unique_fields=["slug"],
        batch_size=200,
    )


def unload(apps, schema_editor):
    Exercise = apps.get_model("planning", "Exercise")
    slugs = [row["slug"] for row in json.loads(DATA.read_text())]
    Exercise.objects.filter(slug__in=slugs).delete()


class Migration(migrations.Migration):
    dependencies = [("planning", "0012_r21_exercise_library")]
    operations = [migrations.RunPython(load, unload)]
