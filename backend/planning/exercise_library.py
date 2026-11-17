"""The exercise library: every movement, with the ones Rohit runs on up front.

Rohit: "in the gym section i need all kind of workouts in which i should be
able to add filter based on musele like calf all workouts related to that, i
need each an every body part exercises ... with gym equipment too", then
"mostly focus on running related exercises and belly fat reduction exercises".

So: the whole catalogue is there and filterable, and two curated collections sit
above it, because a runner opening a 708-exercise list does not want to start by
deciding between forty biceps variations.

The strength programme in planning/strength.py is a different thing and is
untouched: six patterns chosen *for* you and progressed by a ladder. That is a
coach deciding what you do. This is a reference for looking things up.

**On "belly fat reduction".** There is no such exercise, and the app should not
imply there is — see BELLY_NOTE. Spot reduction does not work: crunches build
the muscle under the fat and do nothing to the fat on top of it. What the
collection actually holds is the two things that do move it — trunk work, which
makes you run better, and hard full-body movements, which cost real calories.
Saying so is the difference between a coach and a fitness app.

The muscle vocabulary is RepDB's, which is anatomical (`gastrocnemius`, not
"calves"). GROUPS maps it to the words people filter by.
"""

from __future__ import annotations

#: Anatomical name -> what to call it on screen. RepDB's own vocabulary, pinned
#: here so a filter cannot silently drift from what the rows contain.
MUSCLE_LABEL: dict[str, str] = {
    "gastrocnemius": "Calves", "soleus": "Soleus", "tibialis_anterior": "Shin",
    "quadriceps": "Quads", "hamstrings": "Hamstrings",
    "gluteus_maximus": "Glutes", "gluteus_medius": "Glute medius",
    "adductors": "Inner thigh", "abductors": "Outer hip", "hip_flexors": "Hip flexors",
    "rectus_abdominis": "Abs", "obliques": "Obliques",
    "transverse_abdominis": "Deep core", "erector_spinae": "Lower back",
    "quadratus_lumborum": "QL",
    "latissimus_dorsi": "Lats", "trapezius": "Traps", "rhomboids": "Rhomboids",
    "infraspinatus_teres_minor": "Rotator cuff", "supraspinatus": "Rotator cuff",
    "serratus_anterior": "Serratus",
    "pectoralis_major": "Chest",
    "anterior_deltoid": "Front delt", "lateral_deltoid": "Side delt",
    "posterior_deltoid": "Rear delt",
    "biceps_brachii": "Biceps", "brachialis": "Brachialis",
    "brachioradialis": "Brachioradialis", "triceps_brachii": "Triceps",
    "forearm_flexors": "Forearm flexors", "forearm_extensors": "Forearm extensors",
    "forearms": "Forearms",
}

#: The headings the filter bar groups muscles under.
MUSCLE_GROUPS: dict[str, tuple[str, ...]] = {
    "Legs": ("gastrocnemius", "soleus", "tibialis_anterior", "quadriceps", "hamstrings",
             "gluteus_maximus", "gluteus_medius", "adductors", "abductors", "hip_flexors"),
    "Core": ("rectus_abdominis", "obliques", "transverse_abdominis", "erector_spinae",
             "quadratus_lumborum"),
    "Back": ("latissimus_dorsi", "trapezius", "rhomboids", "serratus_anterior",
             "infraspinatus_teres_minor", "supraspinatus"),
    "Chest": ("pectoralis_major",),
    "Shoulders": ("anterior_deltoid", "lateral_deltoid", "posterior_deltoid"),
    "Arms": ("biceps_brachii", "brachialis", "brachioradialis", "triceps_brachii",
             "forearm_flexors", "forearm_extensors", "forearms"),
}

MUSCLES: tuple[str, ...] = tuple(m for g in MUSCLE_GROUPS.values() for m in g)
GROUP_OF: dict[str, str] = {m: g for g, ms in MUSCLE_GROUPS.items() for m in ms}

#: --- the two collections -----------------------------------------------------

#: What actually carries a runner: the calf complex that ends most beginners'
#: builds, the hip that holds the pelvis level at footstrike, and the trunk that
#: stops the whole thing folding late in a run.
RUNNER_MUSCLES: frozenset[str] = frozenset({
    "gastrocnemius", "soleus", "tibialis_anterior",
    "gluteus_maximus", "gluteus_medius", "hamstrings", "quadriceps",
    "hip_flexors", "adductors", "abductors",
    "erector_spinae", "transverse_abdominis", "obliques",
})

#: Trunk work, plus the hard full-body movements that cost enough calories to
#: matter. NOT "fat burning": see BELLY_NOTE.
BELLY_MUSCLES: frozenset[str] = frozenset({
    "rectus_abdominis", "obliques", "transverse_abdominis", "erector_spinae",
    "quadratus_lumborum", "hip_flexors",
})

#: Categories whose movements raise the heart rate enough to be worth counting
#: toward the second half of that collection.
CONDITIONING_CATEGORIES: frozenset[str] = frozenset({"cardio", "plyometrics"})

COLLECTIONS: dict[str, dict] = {
    "runner": {
        "label": "For running",
        "note": "What carries you: calves and shins, glutes and hamstrings, and the "
                "trunk that stops your form folding at the end of a run.",
    },
    "belly": {
        "label": "Core & midsection",
        "note": "",   # filled from BELLY_NOTE below
    },
}

#: The honest version, shown on the collection rather than buried.
BELLY_NOTE = (
    "You cannot lose fat from one place by training it — crunches build the muscle "
    "under the belly and do nothing to the fat on top. What moves that is the "
    "calorie deficit and the running. These are here because a strong trunk makes "
    "you run better, and the harder full-body ones cost real calories."
)
COLLECTIONS["belly"]["note"] = BELLY_NOTE

LEVELS: tuple[str, ...] = ("beginner", "intermediate", "advanced", "expert")

#: Equipment is RepDB's, which is long and specific (65 values). The filter bar
#: shows only what the library actually holds, so it is built from the rows.
EQUIPMENT_LABEL: dict[str, str] = {
    "": "Bodyweight", "none": "Bodyweight", "pull_up_bar": "Pull-up bar",
    "ez_bar": "EZ bar", "resistance_band": "Resistance band", "loop_band": "Loop band",
    "smith_machine": "Smith machine", "flat_bench": "Bench",
    "suspension_trainer": "Suspension trainer", "bosu_ball": "Bosu",
    "medicine_ball": "Medicine ball", "stability_ball": "Stability ball",
    "foam_roller": "Foam roller", "jump_rope": "Jump rope",
}


def label_for(equipment: str | None) -> str:
    if not equipment:
        return "Bodyweight"
    return EQUIPMENT_LABEL.get(equipment, equipment.replace("_", " ").title())


def muscle_label(muscle: str) -> str:
    return MUSCLE_LABEL.get(muscle, muscle.replace("_", " ").title())


def group_for(muscle: str) -> str | None:
    return GROUP_OF.get(muscle)


def collections_for(primary, secondary, category: str = "") -> list[str]:
    """Which curated collections an exercise belongs to.

    A runner's collection built from secondary muscles too would be most of the
    library — nearly everything involves the trunk somewhere — so the runner cut
    is on PRIMARY muscles only. The midsection one takes the conditioning
    categories as well, because a burpee belongs in it and works no abs by that
    definition.
    """
    primary = set(primary or [])
    out: list[str] = []
    if primary & RUNNER_MUSCLES:
        out.append("runner")
    if (primary & BELLY_MUSCLES) or category in CONDITIONING_CATEGORIES:
        out.append("belly")
    return out
