"""R21: the exercise library — browse and filter every movement.

Rohit: "i need all kind of workouts in which i should be able to add filter
based on musele like calf all workouts related to that, i need each an every
body part exercises ... with gym equipment too".

Two endpoints. `facets` is what the filter bar is built from, with a count
against every value so the UI never offers a filter that returns nothing.
`list` is the filtered, paged results.

The filters compose with AND between kinds and OR within a kind — picking
"calves" and "dumbbell" means dumbbell exercises for calves, while picking
"calves" and "quadriceps" means either. That is what a filter bar is assumed to
do, and the assumption is worth matching rather than explaining.
"""

from __future__ import annotations

from django.db.models import Case, IntegerField, Q, Value, When
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from planning import exercise_library as lib

from .models import Exercise

#: Where the pictures are served from.
MEDIA_PREFIX = "ex"

PAGE_SIZE = 40
MAX_PAGE_SIZE = 100


def exercise_json(row: Exercise, *, full: bool = False) -> dict:
    media = dict(row.media or {})
    # Paths become URLs here rather than in the import, so moving where the
    # files are served from is one change in one place.
    for key in ("anim",):
        if media.get(key):
            media[key] = f"/{MEDIA_PREFIX}/{media[key]}"
    for style in ("classic", "flat"):
        if isinstance(media.get(style), dict):
            media[style] = {k: f"/{MEDIA_PREFIX}/{v}" for k, v in media[style].items()}

    body = {
        "id": row.pk,
        "slug": row.slug,
        "name": row.name,
        "category": row.category,
        "level": row.level,
        "body_part": row.body_part,
        "equipment": row.equipment,
        "equipment_label": lib.label_for(row.equipment),
        "primary_muscles": [lib.muscle_label(m) for m in row.primary_muscles],
        "secondary_muscles": [lib.muscle_label(m) for m in row.secondary_muscles],
        # The raw anatomical names too: the body map highlights by those, and
        # a display label is not a key.
        "primary_keys": row.primary_muscles,
        "secondary_keys": row.secondary_muscles,
        "groups": sorted({g for m in row.primary_muscles if (g := lib.group_for(m))}),
        "collections": row.collections or [],
        "media": media,
    }
    if full:
        body["instructions"] = row.instructions
        body["tips"] = row.tips
        body["met"] = row.met
        body["force"] = row.force
        body["mechanic"] = row.mechanic
    return body


def _filtered(params):
    rows = Exercise.objects.all()

    wanted = [c for c in params.getlist("collection") if c in lib.COLLECTIONS]
    if wanted:
        clause = Q()
        for name in wanted:
            clause |= Q(collections__contains=name)
        rows = rows.filter(clause)

    muscles = [m for m in params.getlist("muscle") if m in lib.MUSCLES]
    if muscles:
        # Primary OR secondary: somebody looking for calf work wants the
        # movements that load the calves, not only the ones named after them.
        clause = Q()
        primary = Q()
        for muscle in muscles:
            clause |= Q(primary_muscles__contains=muscle)
            clause |= Q(secondary_muscles__contains=muscle)
            primary |= Q(primary_muscles__contains=muscle)
        # Movements that work the muscle come before ones that merely involve
        # it. Without this, filtering for calves opened on a list of hamstring
        # exercises — every one a real match, and none of them the answer to
        # the question, which reads as a broken filter rather than a generous
        # one.
        rows = rows.filter(clause).annotate(
            is_primary=Case(When(primary, then=Value(0)), default=Value(1),
                            output_field=IntegerField()),
        ).order_by("is_primary", "name")

    groups = [g for g in params.getlist("group") if g in lib.MUSCLE_GROUPS]
    if groups:
        clause = Q()
        for group in groups:
            for muscle in lib.MUSCLE_GROUPS[group]:
                clause |= Q(primary_muscles__contains=muscle)
        rows = rows.filter(clause)

    # Equipment and category are not validated against a pinned list. RepDB has
    # 65 kinds of kit and adds more; a whitelist here would silently drop a
    # filter the facet endpoint had just offered, which is the worst kind of
    # mismatch because the UI looks right. An unmatched value simply returns
    # nothing, which is the honest answer to "show me exercises with a value
    # that does not exist".
    equipment = [e[:24] for e in params.getlist("equipment")]
    if equipment:
        rows = rows.filter(equipment__in=equipment)

    categories = [c[:24] for c in params.getlist("category")]
    if categories:
        rows = rows.filter(category__in=categories)

    levels = [v for v in params.getlist("level") if v in lib.LEVELS]
    if levels:
        rows = rows.filter(level__in=levels)

    if search := (params.get("q") or "").strip():
        rows = rows.filter(name__icontains=search[:80])

    return rows


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def exercise_facets(request):
    """GET /exercises/facets/ -> the filter bar, with counts.

    Counted against the whole library rather than the current result set. A
    count that changes as you tick boxes is the more sophisticated behaviour
    and the more confusing one: the number beside "Calves" should mean "calf
    exercises exist", not "calf exercises that also match what you have
    already picked", which is a sentence nobody reads a number as.
    """
    rows = list(Exercise.objects.values("primary_muscles", "secondary_muscles",
                                        "equipment", "category", "level", "collections"))

    muscle_counts: dict[str, int] = {}
    group_counts: dict[str, int] = {}
    equipment_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    level_counts: dict[str, int] = {}
    collection_counts: dict[str, int] = {}

    for row in rows:
        touched = set(row["primary_muscles"] or []) | set(row["secondary_muscles"] or [])
        for muscle in touched:
            muscle_counts[muscle] = muscle_counts.get(muscle, 0) + 1
        for group in {g for m in (row["primary_muscles"] or []) if (g := lib.group_for(m))}:
            group_counts[group] = group_counts.get(group, 0) + 1
        key = row["equipment"] or ""
        equipment_counts[key] = equipment_counts.get(key, 0) + 1
        if row["category"]:
            category_counts[row["category"]] = category_counts.get(row["category"], 0) + 1
        if row["level"]:
            level_counts[row["level"]] = level_counts.get(row["level"], 0) + 1
        for name in row["collections"] or []:
            collection_counts[name] = collection_counts.get(name, 0) + 1

    return Response({
        "total": len(rows),
        # First, because a runner opening a 708-exercise list does not want to
        # start by choosing between forty biceps variations.
        "collections": [
            {"key": key, "label": spec["label"], "note": spec["note"],
             "count": collection_counts.get(key, 0)}
            for key, spec in lib.COLLECTIONS.items()
        ],
        "groups": [
            {"key": group, "label": group, "count": group_counts.get(group, 0),
             "muscles": [{"key": m, "label": lib.muscle_label(m),
                          "count": muscle_counts.get(m, 0)}
                         for m in muscles if muscle_counts.get(m)]}
            for group, muscles in lib.MUSCLE_GROUPS.items()
        ],
        "equipment": sorted(
            ({"key": key, "label": lib.label_for(key), "count": count}
             for key, count in equipment_counts.items() if count),
            key=lambda e: -e["count"],
        ),
        "categories": sorted(
            ({"key": c, "label": c.replace("_", " ").title(), "count": n}
             for c, n in category_counts.items()), key=lambda e: -e["count"]),
        "levels": [{"key": v, "label": v.title(), "count": level_counts[v]}
                   for v in lib.LEVELS if level_counts.get(v)],
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def exercise_list(request):
    """GET /exercises/?muscle=calves&equipment=dumbbell&q=&page= -> results."""
    params = request.query_params
    rows = _filtered(params)
    total = rows.count()

    try:
        page = max(int(params.get("page") or 1), 1)
    except ValueError:
        page = 1
    try:
        size = min(max(int(params.get("page_size") or PAGE_SIZE), 1), MAX_PAGE_SIZE)
    except ValueError:
        size = PAGE_SIZE

    start = (page - 1) * size
    window = list(rows[start:start + size])
    return Response({
        "total": total,
        "page": page,
        "page_size": size,
        "has_more": start + len(window) < total,
        "results": [exercise_json(row) for row in window],
    })


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def exercise_detail(request, slug: str):
    """GET /exercises/{slug}/ -> one movement, with its instructions."""
    row = Exercise.objects.filter(slug=slug).first()
    if row is None:
        return Response({"detail": "No such exercise."}, status=404)
    return Response(exercise_json(row, full=True))
