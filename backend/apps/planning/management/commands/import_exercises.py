"""Load the exercise library from the RepDB dataset.

    python manage.py import_exercises --json <exercises.json>

Data only; the pictures are copied into frontend/public/ex/ as a separate step
because they are static files, not rows.

**Why RepDB and not free-exercise-db.** The library was built on
free-exercise-db first — 876 exercises, public domain, and two photographs of a
man in a gym per exercise. Rohit did not want photographs, and the
muscle-highlighted figures he did want are RepDB's. Its ids address its own
images directly, so every exercise gets the best media that exists for it with
no name-matching in between; matching the two datasets by name landed 6 of 30.

Licensing, because it is not uniform and the distinction matters:

* The 708-exercise dataset and its flat illustrations are RepDB's free tier —
  free for personal and commercial use, requiring a visible
  "Exercise data by RepDB (repdb.co)" credit.
* The classic stills and the animations come from the preview pack, which is
  CC BY-NC 4.0: personal and non-commercial use only. Rohit's app is his own
  and is not public, which is what that licence permits. If it ever ships
  commercially those two directories have to go and the paid bundle replaces
  them; the `media` field is the only thing that would change.

Idempotent on `slug` (RepDB's id), so re-running updates rows in place.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.planning.models import Exercise
from planning import exercise_library as lib

DATA_URL = "https://raw.githubusercontent.com/RepDB/exercise-dataset/main/exercises.json"


class Command(BaseCommand):
    help = "Import the RepDB exercise library."

    def add_arguments(self, parser):
        parser.add_argument("--json", help="Local exercises.json instead of fetching.")
        parser.add_argument("--media", help="Directory holding anim/ classic/ flat/, "
                                            "so the import records only media that exists.")
        parser.add_argument("--limit", type=int)

    def handle(self, *args, **options):
        raw = self._load(options.get("json"))
        items = raw if isinstance(raw, list) else (
            raw.get("exercises") or next(iter(raw.values()))
        )
        if options.get("limit"):
            items = items[: options["limit"]]

        media_root = Path(options["media"]) if options.get("media") else None
        created = updated = 0
        have = {"anim": 0, "classic": 0, "flat": 0, "none": 0}
        in_collection = {"runner": 0, "belly": 0}

        for entry in items:
            slug = (entry.get("id") or "").strip()[:160]
            if not slug:
                continue
            primary = [m for m in entry.get("primary_muscles") or [] if m in lib.MUSCLES]
            secondary = [m for m in entry.get("secondary_muscles") or [] if m in lib.MUSCLES]
            category = (entry.get("category") or "")[:24]
            sets = lib.collections_for(primary, secondary, category)
            for name in sets:
                in_collection[name] = in_collection.get(name, 0) + 1

            media = self._media(slug, entry, media_root)
            have[media.get("best") or "none"] += 1

            with transaction.atomic():
                _, was_created = Exercise.objects.update_or_create(
                    slug=slug,
                    defaults={
                        "name": (entry.get("name_en") or "")[:160],
                        "category": category,
                        "level": (entry.get("difficulty") or "")[:16],
                        "equipment": (entry.get("equipment") or "")[:24],
                        "body_part": (entry.get("body_part") or "")[:16],
                        "force": (entry.get("force_type") or "")[:16],
                        "mechanic": (entry.get("mechanic") or "")[:16],
                        "primary_muscles": primary,
                        "secondary_muscles": secondary,
                        "instructions": [str(i) for i in entry.get("instructions_en") or []],
                        "tips": [str(t) for t in entry.get("tips_en") or []],
                        "met": entry.get("met"),
                        "collections": sets,
                        "media": media,
                    },
                )
            created += was_created
            updated += not was_created

        self.stdout.write(self.style.SUCCESS(f"{created} created, {updated} updated."))
        self.stdout.write(f"  media: {have}")
        self.stdout.write(f"  collections: {in_collection}")

    def _media(self, slug: str, entry: dict, root: Path | None) -> dict:
        """Best available media for one exercise.

        Only records a path when the file is actually on disk, when a media
        directory is given. A row claiming an animation that was never copied
        is a broken image on the one screen this feature exists for.
        """
        def exists(rel: str) -> bool:
            return root is None or (root / rel).is_file()

        out: dict = {}
        if exists(f"anim/{slug}.webp"):
            out["anim"] = f"anim/{slug}.webp"

        for style in ("classic", "flat"):
            start, peak = f"{style}/{slug}-start.webp", f"{style}/{slug}-peak.webp"
            main = f"{style}/{slug}-main.webp"
            if exists(start) and exists(peak):
                out[style] = {"start": start, "peak": peak}
            elif exists(main):
                out[style] = {"main": main}

        # Flat paths are also in the dataset; trust the files on disk over the
        # manifest when both are available, because the files are what serve.
        if "flat" not in out and root is None:
            flat = ((entry.get("images") or {}).get("flat")) or {}
            if flat:
                out["flat"] = {k: f"flat/{Path(v).name}" for k, v in flat.items()}

        out["best"] = "anim" if "anim" in out else "classic" if "classic" in out \
            else "flat" if "flat" in out else None
        return out

    def _load(self, local: str | None):
        if local:
            return json.loads(Path(local).read_text())
        try:
            with urllib.request.urlopen(DATA_URL, timeout=60) as response:
                return json.loads(response.read())
        except urllib.error.URLError as exc:
            raise CommandError(f"Could not fetch the dataset: {exc}") from exc
