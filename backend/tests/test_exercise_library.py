"""The exercise library: every movement, filtered down to the one you want.

Rohit: "in the gym section i need all kind of workouts in which i should be
able to add filter based on musele like calf all workouts related to that, i
need each an every body part exercises ... not only legs whole body mussels all
exercises with gym equipment too".

The gym tab had thirty movements, because it only ever held the six patterns
the strength programme progresses. That is the right size for a programme and
the wrong size for a reference.
"""

from __future__ import annotations

import pytest

from apps.planning.models import Exercise
from planning import exercise_library as lib


def make(slug, name, *, primary=(), secondary=(), equipment="dumbbell",
         category="strength", level="beginner", media=None):
    from planning import exercise_library as lib

    return Exercise.objects.create(
        slug=slug, name=name, category=category, level=level, equipment=equipment,
        primary_muscles=list(primary), secondary_muscles=list(secondary),
        instructions=["Do the thing."], tips=["Keep the trunk braced."],
        collections=lib.collections_for(primary, secondary, category),
        media=media if media is not None else {
            "best": "flat", "flat": {"start": f"flat/{slug}-start.webp",
                                     "peak": f"flat/{slug}-peak.webp"},
        },
    )


@pytest.fixture
def library(db):
    # The real 708 ship in a data migration, so the test database already has
    # them. These tests are about filter behaviour over a known small set, and
    # they assert exact totals; they start from an empty table on purpose.
    Exercise.objects.all().delete()
    make("calf-raise", "Calf Raise", primary=["gastrocnemius"], equipment="")
    make("seated-calf-raise", "Seated Calf Raise", primary=["gastrocnemius"],
         equipment="machine")
    make("dumbbell-calf-raise", "Dumbbell Calf Raise", primary=["gastrocnemius"],
         media={"best": "anim", "anim": "anim/dumbbell-calf-raise.webp"})
    # Loads the calves without being a calf exercise — the case that decides
    # whether the filter is generous or merely noisy.
    make("box-jump", "Box Jump", primary=["quadriceps"], secondary=["gastrocnemius"],
         equipment="", category="plyometrics")
    make("bench-press", "Bench Press", primary=["pectoralis_major"],
         secondary=["triceps_brachii"], equipment="barbell")
    make("pull-up", "Pull Up", primary=["latissimus_dorsi"],
         secondary=["biceps_brachii"], equipment="pull_up_bar")


# --- the vocabulary ----------------------------------------------------------


def test_every_muscle_belongs_to_a_group():
    """The UI groups the seventeen muscles under six headings. One without a
    group would be a filter chip nobody could ever reach."""
    for muscle in lib.MUSCLES:
        assert lib.group_for(muscle), muscle


def test_the_whole_body_is_covered_not_just_legs():
    """"not only legs whole body mussels"."""
    assert set(lib.MUSCLE_GROUPS) == {"Legs", "Back", "Chest", "Arms", "Shoulders", "Core"}


@pytest.mark.django_db
def test_real_gym_equipment_is_in_the_library(library):
    """"with gym equipment too" — the programme's own ladders are deliberately
    bodyweight and dumbbell only, and this is the half they leave out."""
    rows = Exercise.objects.values_list("equipment", flat=True)
    assert "barbell" in set(rows)


# --- filtering ---------------------------------------------------------------


@pytest.mark.django_db
def test_a_muscle_filter_finds_everything_that_works_it(api, library):
    """"all workouts related to that" — including the box jump, which loads the
    calves without being named after them."""
    body = api.get("/api/exercises/?muscle=gastrocnemius").json()
    names = [x["name"] for x in body["results"]]
    assert "Box Jump" in names
    assert body["total"] == 4


@pytest.mark.django_db
def test_the_exercises_that_work_the_muscle_come_first(api, library):
    """Filtering for calves opened on a list of quadriceps exercises — every
    one a real match, none of them the answer, which reads as a broken filter
    rather than a generous one."""
    results = api.get("/api/exercises/?muscle=gastrocnemius").json()["results"]
    assert "gastrocnemius" in results[0]["primary_keys"]
    assert results[-1]["name"] == "Box Jump"


@pytest.mark.django_db
def test_muscle_and_equipment_narrow_together(api, library):
    """Across kinds the filters are AND: "calf exercises I can do with a
    dumbbell", not "calf exercises or dumbbell exercises"."""
    body = api.get("/api/exercises/?muscle=gastrocnemius&equipment=dumbbell").json()
    assert [x["name"] for x in body["results"]] == ["Dumbbell Calf Raise"]


@pytest.mark.django_db
def test_two_muscles_widen_together(api, library):
    """Within a kind they are OR, which is what a filter bar is assumed to do."""
    body = api.get("/api/exercises/?muscle=gastrocnemius&muscle=pectoralis_major").json()
    assert body["total"] == 5


@pytest.mark.django_db
def test_search_matches_the_name(api, library):
    body = api.get("/api/exercises/?q=calf").json()
    assert body["total"] == 3


@pytest.mark.django_db
def test_an_unknown_muscle_is_ignored_rather_than_erroring(api, library):
    """A filter value the vocabulary does not hold cannot return rows, and a
    500 from a stale bookmark is a worse answer than the whole library."""
    body = api.get("/api/exercises/?muscle=gluteus_fictional").json()
    assert body["total"] == 6


# --- facets ------------------------------------------------------------------


@pytest.mark.django_db
def test_the_filter_bar_carries_counts(api, library):
    """A filter that would return an empty screen should say so before it is
    tapped, not after."""
    body = api.get("/api/exercises/facets/").json()
    assert body["total"] == 6
    legs = next(g for g in body["groups"] if g["key"] == "Legs")
    calves = next(m for m in legs["muscles"] if m["key"] == "gastrocnemius")
    assert calves["count"] == 4


@pytest.mark.django_db
def test_equipment_with_nothing_behind_it_is_not_offered(api, library):
    """Twelve kinds of kit exist in the vocabulary; only the ones with rows
    should reach the bar."""
    body = api.get("/api/exercises/facets/").json()
    offered = {e["key"] for e in body["equipment"]}
    assert offered == {"", "machine", "dumbbell", "barbell", "pull_up_bar"}


# --- one exercise ------------------------------------------------------------


@pytest.mark.django_db
def test_the_detail_carries_the_instructions_and_the_list_does_not(api, library):
    """A grid of 876 cards does not need every step of every movement; one
    open exercise does."""
    row = api.get("/api/exercises/?q=Bench").json()["results"][0]
    assert "instructions" not in row

    detail = api.get("/api/exercises/bench-press/").json()
    assert detail["instructions"]
    assert detail["groups"] == ["Chest"]


@pytest.mark.django_db
def test_images_are_served_from_our_own_origin(api, library):
    """Production's CSP is `img-src 'self' data: blob:` plus map tiles, so a
    hotlinked dataset URL would be blocked in the browser with no error anyone
    sees. The paths must be local ones."""
    row = api.get("/api/exercises/?q=Bench").json()["results"][0]
    for src in row["media"]["flat"].values():
        assert src.startswith("/ex/")


@pytest.mark.django_db
def test_a_missing_exercise_is_a_404(api, library):
    assert api.get("/api/exercises/no-such-thing/").status_code == 404


@pytest.mark.django_db
def test_the_library_needs_a_login(client, library):
    assert client.get("/api/exercises/").status_code in (401, 403)


# --- paging ------------------------------------------------------------------


@pytest.mark.django_db
def test_results_are_paged(api, library):
    first = api.get("/api/exercises/?page_size=2").json()
    assert len(first["results"]) == 2
    assert first["has_more"] is True
    assert first["total"] == 6

    last = api.get("/api/exercises/?page_size=2&page=3").json()
    assert last["has_more"] is False


@pytest.mark.django_db
def test_a_silly_page_size_cannot_pull_the_whole_table(api, library):
    body = api.get("/api/exercises/?page_size=100000").json()
    assert body["page_size"] <= 100


# --- the two curated collections ---------------------------------------------
#
# Rohit: "mostly focus on running related exercises and belly fat reduction
# exercises".


def test_what_carries_a_runner_is_in_the_runner_collection():
    """Calves and shins, hips, hamstrings, trunk. Not biceps."""
    assert lib.collections_for(["gastrocnemius"], [], "strength") == ["runner"]
    assert lib.collections_for(["gluteus_medius"], [], "strength") == ["runner"]
    assert lib.collections_for(["biceps_brachii"], [], "strength") == []


def test_the_runner_cut_is_on_primary_muscles_only():
    """Nearly everything involves the trunk somewhere, so a collection built
    from secondary muscles too would be most of the library — which is not a
    collection, it is the library with an extra tap."""
    assert lib.collections_for(["biceps_brachii"], ["erector_spinae"], "strength") == []


def test_hard_conditioning_counts_toward_the_midsection_collection():
    """A burpee belongs in it and works no abs by the muscle definition."""
    assert "belly" in lib.collections_for(["quadriceps"], [], "plyometrics")
    assert "belly" in lib.collections_for(["rectus_abdominis"], [], "strength")


def test_the_midsection_collection_refuses_to_promise_spot_reduction():
    """The honest version is the whole point of the note. Crunches build the
    muscle under the fat and do nothing to the fat on top; saying so is the
    difference between a coach and a fitness app."""
    note = lib.COLLECTIONS["belly"]["note"].lower()
    assert "cannot lose fat from one place" in note
    assert "deficit" in note


@pytest.mark.django_db
def test_a_collection_filters_the_list(api, library):
    body = api.get("/api/exercises/?collection=runner").json()
    names = {x["name"] for x in body["results"]}
    assert "Calf Raise" in names
    assert "Bench Press" not in names


@pytest.mark.django_db
def test_the_collections_lead_the_filter_bar_with_their_notes(api, library):
    body = api.get("/api/exercises/facets/").json()
    keys = [c["key"] for c in body["collections"]]
    assert keys == ["runner", "belly"]
    assert all("count" in c for c in body["collections"])
    assert next(c for c in body["collections"] if c["key"] == "belly")["note"]


# --- media --------------------------------------------------------------------


@pytest.mark.django_db
def test_an_exercise_with_a_real_animation_reports_it_as_best(api, library):
    """The three tiers exist so no caller has to know which an exercise has."""
    row = api.get("/api/exercises/?q=Dumbbell%20Calf").json()["results"][0]
    assert row["media"]["best"] == "anim"
    assert row["media"]["anim"].startswith("/ex/anim/")


@pytest.mark.django_db
def test_everything_else_still_has_a_picture(api, library):
    """678 of the 708 have no animation, and a library where most entries show
    an empty box is not a library."""
    body = api.get("/api/exercises/?page_size=100").json()
    assert body["results"]
    for row in body["results"]:
        assert row["media"].get("best"), row["name"]


# --- the data actually ships --------------------------------------------------


@pytest.mark.django_db
def test_the_library_is_not_empty_on_a_fresh_database():
    """The bug this file did not catch the first time.

    The table and the pictures both reached production and the rows did not:
    they only ever existed in a developer's database after running
    `import_exercises` by hand, so the screen came up saying "0 exercises" with
    every filter reading zero. The rows ship in a data migration now, and this
    is the assertion that they are still in it.
    """
    assert Exercise.objects.count() == 708


@pytest.mark.django_db
def test_the_shipped_rows_carry_their_pictures_and_collections():
    """A row without media is a card with an empty box on the one screen this
    feature exists for."""
    assert Exercise.objects.filter(media__best="anim").count() == 30
    assert Exercise.objects.filter(media__best=None).count() == 0
    assert Exercise.objects.filter(collections__contains="runner").count() > 300
    assert Exercise.objects.filter(collections__contains="belly").count() > 100


@pytest.mark.django_db
def test_every_shipped_media_path_points_at_a_file_the_frontend_has():
    """The paths are written at import time from files on disk, and the files
    live in a different part of the repo. Nothing but this checks they agree."""
    from pathlib import Path as P

    root = P(__file__).resolve().parents[2] / "frontend" / "public" / "ex"
    if not root.is_dir():          # frontend not present in this checkout
        pytest.skip("frontend/public/ex not in this checkout")

    missing = []
    for row in Exercise.objects.all()[:120]:
        media = row.media or {}
        if media.get("anim") and not (root / media["anim"]).is_file():
            missing.append(media["anim"])
        for style in ("classic", "flat"):
            for path in (media.get(style) or {}).values():
                if not (root / path).is_file():
                    missing.append(path)
    assert not missing, missing[:5]
