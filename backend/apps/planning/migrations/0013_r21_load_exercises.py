"""Loaded the exercise library. Now a no-op, kept because it has shipped.

This filled the Exercise table with 708 rows read from a JSON file beside it.
The library was removed a few days later — a whole tab for a reference nobody
opened — and the file went with it, which would make this migration crash on
any fresh database replaying history.

It cannot be deleted: it is applied in production, and a migration that
vanishes from the tree leaves every database that ran it with a record of
something that no longer exists. So it stays, does nothing, and says why. The
migration after this one drops the table it used to fill.
"""

from __future__ import annotations

from django.db import migrations


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("planning", "0012_r21_exercise_library")]
    operations = [migrations.RunPython(noop, noop)]
