"""R18: parse every fact that existed before R18 now, explicitly — plan-affecting values
(run days, long-run day, runs per week) are stored needs_review (never applied without the
athlete's yes); sleep need / run time / loop distance apply as usual (by confidence)."""

from django.db import migrations
from django.utils import timezone

PLAN_KEYS = ("available_days", "long_run_day", "runs_per_week")


def forwards(apps, schema_editor):
    from analysis import fact_params as parser

    MemoryFact = apps.get_model("coaching", "MemoryFact")
    FactParameter = apps.get_model("coaching", "FactParameter")
    now = timezone.now()
    for fact in MemoryFact.objects.select_related("athlete").iterator():
        athlete = fact.athlete
        explicit = (athlete.profile_settings or {}).get("available_days", {}).get(
            "value", athlete.available_days)
        FactParameter.objects.filter(fact=fact).delete()
        found = parser.parse(fact.text or "", current_days=explicit)
        if not found:
            # Nothing the parser reads: left for the lazy parse (AI fallback when it looks
            # parameter-like) — which treats it as not user-authored, like here.
            MemoryFact.objects.filter(pk=fact.pk).update(params_text="", parse_pending=False)
            continue
        for p in found:
            note = ""
            if p.key in PLAN_KEYS:
                review = True
                current = getattr(athlete, p.key)
                current = parser.display(p.key, current) if current is not None else "not set"
                note = (f"Your settings: {current}; this fact says "
                        f"{parser.display(p.key, p.value)}.")[:200]
            else:
                review = p.confidence < parser.REVIEW_BELOW
            FactParameter.objects.create(
                athlete_id=fact.athlete_id, fact=fact, key=p.key, value=p.value, unit=p.unit,
                confidence=p.confidence, source="parser", needs_review=review,
                status="needs_review" if review else "active", conflict=note,
                effective_at=fact.updated_at or fact.created_at or now)
        MemoryFact.objects.filter(pk=fact.pk).update(params_text=fact.text, parse_pending=False)


class Migration(migrations.Migration):
    dependencies = [("coaching", "0013_r18"), ("athletes", "0012_r18")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
