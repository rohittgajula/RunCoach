"""Garmin Connect sync.

Garmin has no personal API — the Connect Developer Program requires a legal entity,
rejects personal use, and is currently on hold — so this rides the unofficial
`garminconnect` client against a saved OAuth token. Three consequences shape it:

1. Auth can fail at any time (expired token, revoked session, IP rate limit). Every
   failure is classified and surfaced verbatim, because a sync that silently reports
   success is worse than one that visibly fails.
2. Downloads are the ORIGINAL .fit file, not the JSON summary. The summary has no
   per-second series, so it cannot support run/walk segmentation.
3. Garmin rate-limits by IP, and on a hosted multi-athlete deployment every sync
   leaves from one address. A 429 is therefore treated as a stop signal for the whole
   run, not something to retry past — continuing lengthens the block for everyone.
   See docs/HOSTING.md.
"""

from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from django.core.files.base import ContentFile
from django.utils import timezone

from apps.athletes.models import Athlete

from .models import RawFitFile
from .services import DuplicateActivity, ingest_fit

logger = logging.getLogger(__name__)


class GarminAuthError(Exception):
    """Token missing, expired, or rejected. The athlete must connect again."""


class GarminRateLimited(Exception):
    """Garmin returned 429. Back off; retrying immediately makes it worse."""


@dataclass
class SyncResult:
    imported: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    activity_ids: list[int] = field(default_factory=list)
    wellness_days: int = 0

    def as_dict(self) -> dict:
        return {
            "imported": self.imported,
            "skipped": self.skipped,
            "failed": self.failed,
            "errors": self.errors,
            "activity_ids": self.activity_ids,
            "wellness_days": self.wellness_days,
        }


def _client(athlete: Athlete):
    from garminconnect import Garmin

    token_dir = Path(athlete.token_dir)
    # garth writes several files here. An empty directory means a login that claimed
    # to succeed actually wrote nothing — a real failure mode, not a hypothetical.
    if not token_dir.is_dir() or not any(token_dir.iterdir()):
        raise GarminAuthError(
            "No Garmin session found. Connect your Garmin account first."
        )

    client = Garmin()
    try:
        client.login(str(token_dir))
    except Exception as exc:  # noqa: BLE001 — classify, then re-raise
        message = str(exc)
        if "429" in message or "TooManyRequests" in message:
            raise GarminRateLimited(f"Garmin rate-limited this network: {message}") from exc
        raise GarminAuthError(f"Garmin rejected the saved session: {message}") from exc
    return client


def _extract_fit(payload: bytes) -> tuple[bytes, str] | None:
    """ORIGINAL downloads arrive as a zip containing one .fit."""
    if payload[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for name in archive.namelist():
                if name.lower().endswith(".fit"):
                    return archive.read(name), Path(name).name
        return None
    # Some endpoints hand back the .fit directly.
    if payload[8:12] == b".FIT":
        return payload, "activity.fit"
    return None


HISTORY_MONTHS = 12
PAGE_SIZE = 100
INCREMENTAL_PAGE = 20
INCREMENTAL_MAX = 100
# Downloads per sync. The backfill can be hundreds of files; spreading it over several
# syncs keeps one run from looking like a scrape to Garmin's per-IP limiter.
MAX_DOWNLOADS_PER_SYNC = 60


def _entry_date(entry: dict):
    import datetime as dt

    raw = entry.get("startTimeLocal") or entry.get("startTimeGMT") or ""
    try:
        return dt.date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _list_call(client, start: int, limit: int) -> list:
    try:
        return client.get_activities(start, limit) or []
    except Exception as exc:  # noqa: BLE001
        if "429" in str(exc) or "TooManyRequests" in str(exc):
            raise GarminRateLimited(str(exc)) from exc
        raise


def list_new_activities(client, known: set, *, backfill: bool, cutoff) -> tuple[list, bool]:
    """Listing entries worth looking at, newest first, and whether the walk finished.

    Backfill (first sync, or one not yet completed): page back PAGE_SIZE at a time
    until an entry is older than `cutoff` or Garmin runs out. Otherwise: pages of
    INCREMENTAL_PAGE until a page contains an already-known id, at most INCREMENTAL_MAX.
    """
    entries: list = []
    start = 0
    if backfill:
        while True:
            page = _list_call(client, start, PAGE_SIZE)
            for entry in page:
                day = _entry_date(entry)
                if day is not None and day < cutoff:
                    return entries, True
                entries.append(entry)
            if len(page) < PAGE_SIZE:
                return entries, True
            start += PAGE_SIZE

    while start < INCREMENTAL_MAX:
        page = _list_call(client, start, INCREMENTAL_PAGE)
        hit_known = False
        for entry in page:
            if entry.get("activityId") in known:
                hit_known = True
                break
            entries.append(entry)
        if hit_known or len(page) < INCREMENTAL_PAGE:
            break
        start += INCREMENTAL_PAGE
    return entries, True


def sync_athlete(athlete: Athlete, limit: int | None = None) -> SyncResult:
    """Pull activities and ingest any that are new.

    Idempotent on two independent levels — Garmin's activity id and the file's content
    hash — so re-running is always safe and never duplicates. Two layers rather than
    one because either can fail alone: a manual upload has no Garmin id, and Garmin
    could in principle renumber.

    The first sync (and every sync until the backfill completes) reaches back
    HISTORY_MONTHS; later ones stop at the first activity already stored.
    """
    import datetime as dt

    from garminconnect import Garmin

    from apps.activities.models import Activity

    result = SyncResult()
    client = _client(athlete)

    known = set(
        Activity.objects.filter(athlete=athlete, garmin_activity_id__isnull=False)
        .values_list("garmin_activity_id", flat=True)
    )
    backfill = not athlete.garmin_backfilled or not known
    # R17: activities the athlete deleted here never come back.
    from apps.activities.deletion import check_listing, tombstoned_garmin_ids

    deleted = tombstoned_garmin_ids(athlete)
    cutoff = athlete.local_today - dt.timedelta(days=round(HISTORY_MONTHS * 30.4))
    listing, _ = list_new_activities(client, known, backfill=backfill, cutoff=cutoff)
    if backfill and known:
        # A full listing back to the cutoff: anything we hold that it lacks was
        # deleted in Garmin — a review question, never an automatic delete.
        try:
            check_listing(athlete, listing, page_full=False)
        except Exception:  # noqa: BLE001
            logger.exception("garmin deletion check failed for %s", athlete.pk)
    if limit:
        listing = listing[:limit]
    downloads = 0
    capped = False

    for entry in listing:
        activity_id = entry.get("activityId")
        if activity_id is None:
            continue
        if activity_id in known or activity_id in deleted:
            result.skipped += 1
            continue
        if downloads >= MAX_DOWNLOADS_PER_SYNC:
            capped = True
            break
        downloads += 1

        try:
            payload = client.download_activity(
                activity_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL
            )
            extracted = _extract_fit(payload)
            if extracted is None:
                result.failed += 1
                result.errors.append(f"{activity_id}: download was not a .fit file")
                continue

            data, filename = extracted
            digest = RawFitFile.hash_bytes(data)
            # Second idempotency layer: the same bytes, however they arrived.
            if RawFitFile.objects.filter(athlete=athlete, sha256=digest).exists():
                result.skipped += 1
                continue

            raw = RawFitFile.objects.create(
                athlete=athlete,
                file=ContentFile(data, name=f"{activity_id}_{filename}"),
                original_name=filename,
                sha256=digest,
                size_bytes=len(data),
            )
            activity = ingest_fit(raw, garmin_activity_id=activity_id)
            result.imported += 1
            result.activity_ids.append(activity.pk)

            # Hand straight to the metrics queue rather than waiting for the sweep.
            # Queued, not called: segmentation must not be able to fail a sync.
            try:
                from apps.activities.tasks import derive_one

                derive_one.delay(activity.pk)
            except Exception:  # noqa: BLE001 — no broker in tests or a one-off script
                logger.debug("could not queue derivation for %s", activity.pk)

        except DuplicateActivity:
            result.skipped += 1
        except Exception as exc:  # noqa: BLE001 — one bad activity must not stop the sync
            if "429" in str(exc):
                result.errors.append("Garmin rate-limited the download; stopping early.")
                break
            logger.exception("garmin sync failed for activity %s", activity_id)
            result.failed += 1
            result.errors.append(f"{activity_id}: {exc}")

    # Wellness is pulled after activities so a rate limit costs the cheaper half.
    try:
        from .garmin_wellness import sync_wellness

        wellness = sync_wellness(athlete, client)
        result.wellness_days = wellness["days_written"]
        if wellness.get("rate_limited"):
            result.errors.append("Garmin rate-limited the wellness download; stopping early.")
    except Exception as exc:  # noqa: BLE001 — activities already landed; keep them
        logger.exception("wellness sync failed")
        result.errors.append(f"wellness: {exc}")

    athlete.garmin_connected = True
    athlete.garmin_last_sync = timezone.now()
    fields = ["garmin_connected", "garmin_last_sync"]
    rate_limited = any("rate-limited" in e for e in result.errors)
    if backfill and not capped and not rate_limited:
        athlete.garmin_backfilled = True
        fields.append("garmin_backfilled")
    athlete.save(update_fields=fields)
    return result


def reimport_one(athlete: Athlete, garmin_activity_id: int) -> dict:
    """R17: fetch one activity again (after its tombstone was removed)."""
    from garminconnect import Garmin

    from apps.activities.models import Activity

    existing = Activity.objects.filter(athlete=athlete,
                                       garmin_activity_id=garmin_activity_id).first()
    if existing is not None:
        return {"activity_id": existing.pk, "detail": "Already here."}
    client = _client(athlete)
    try:
        payload = client.download_activity(
            garmin_activity_id, dl_fmt=Garmin.ActivityDownloadFormat.ORIGINAL)
    except Exception as exc:  # noqa: BLE001
        if "429" in str(exc) or "TooManyRequests" in str(exc):
            raise GarminRateLimited(str(exc)) from exc
        return {"activity_id": None, "detail": "Garmin no longer has this activity."}
    extracted = _extract_fit(payload) if payload else None
    if extracted is None:
        return {"activity_id": None, "detail": "Garmin no longer has this activity."}
    data, filename = extracted
    digest = RawFitFile.hash_bytes(data)
    raw = RawFitFile.objects.filter(athlete=athlete, sha256=digest).first()
    if raw is None:
        raw = RawFitFile.objects.create(
            athlete=athlete, file=ContentFile(data, name=f"{garmin_activity_id}_{filename}"),
            original_name=filename, sha256=digest, size_bytes=len(data))
    try:
        activity = ingest_fit(raw, garmin_activity_id=garmin_activity_id)
    except DuplicateActivity:
        return {"activity_id": None, "detail": "Already here."}
    from apps.activities.services import derive

    try:
        derive(activity)
    except Exception:  # noqa: BLE001 — the beat re-derives anything stale
        logger.exception("derive after reimport failed for %s", activity.pk)
    return {"activity_id": activity.pk, "detail": "Re-imported from Garmin."}


def check_connection(athlete: Athlete) -> dict:
    """Cheap probe for real connection state.

    Deliberately does not trust the stored `garmin_connected` flag — it re-checks,
    because the failure mode here is a token that looks present but no longer works.
    """
    try:
        client = _client(athlete)
        return {
            "connected": True,
            "name": client.get_full_name(),
            "error": "",
            "last_sync": athlete.garmin_last_sync,
        }
    except (GarminAuthError, GarminRateLimited) as exc:
        return {"connected": False, "name": "", "error": str(exc),
                "last_sync": athlete.garmin_last_sync}
    except Exception as exc:  # noqa: BLE001
        return {"connected": False, "name": "", "error": str(exc),
                "last_sync": athlete.garmin_last_sync}
