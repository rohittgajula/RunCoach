"""R13 §15: "Export my data" — a ZIP of CSVs plus the settings as JSON.

* `POST /export/` queues the build (Celery, metrics queue) — at most one per hour.
* The ZIP is written to the media volume under `exports/athlete_<id>/` with a random
  name. That directory is never served publicly (config/urls.py keeps it out of the
  DEBUG media route; production serves no media at all).
* `GET /export/{id}/download/?token=` needs the signed-in owner AND the one-time token
  (an HMAC of the export's id and creation time with SECRET_KEY — never stored). It
  works once and for 24 h; the file is deleted on download, on expiry (hourly cleanup)
  and with the account.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import logging
import secrets
import zipfile
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import FileResponse
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import DataExport

logger = logging.getLogger(__name__)

EXPORT_DIR = "exports"
RATE_WINDOW = dt.timedelta(hours=1)
VALID_FOR = dt.timedelta(hours=24)
SKIP_FIELDS = {"athlete", "raw", "file", "photo", "user"}


def export_root() -> Path:
    return Path(settings.MEDIA_ROOT) / EXPORT_DIR


def athlete_dir(athlete_id: int) -> Path:
    return export_root() / f"athlete_{athlete_id}"


def token_for(export: DataExport) -> str:
    return salted_hmac("runcoach.export.v1", f"{export.pk}:{export.created_at.isoformat()}",
                       algorithm="sha256").hexdigest()[:48]


def export_json(export: DataExport) -> dict:
    status_ = export.status
    if status_ == DataExport.Status.READY and export.expires_at and \
            export.expires_at <= timezone.now():
        status_ = DataExport.Status.EXPIRED
    url = None
    if status_ == DataExport.Status.READY:
        url = f"/api/export/{export.pk}/download/?token={token_for(export)}"
    return {"id": export.pk, "status": status_, "created_at": export.created_at,
            "finished_at": export.finished_at, "size_bytes": export.size_bytes,
            "expires_at": export.expires_at, "download_url": url, "error": export.error}


# --- building -------------------------------------------------------------------------

def _cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str, separators=(",", ":"))
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    return value


def _fields(model) -> list[str]:
    out = []
    for f in model._meta.concrete_fields:
        if f.name in SKIP_FIELDS:
            continue
        out.append(f.attname if f.is_relation else f.name)
    return out


def _csv(queryset, fields: list[str] | None = None) -> str:
    fields = fields or _fields(queryset.model)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(fields)
    for row in queryset.values_list(*fields).iterator(chunk_size=500):
        writer.writerow([_cell(v) for v in row])
    return buffer.getvalue()


def tables(athlete) -> dict[str, tuple]:
    """file name -> (queryset, fields or None). Every queryset filtered on the athlete."""
    from apps.activities.models import Activity, ActivityMetrics, RunReview, Segment
    from apps.athletes.models import MetricEntry
    from apps.diet.models import Meal, WaterLog
    from apps.habits.models import CravingLog, HabitLog
    from apps.health.models import MonthlyReport, MoodLog, PainReport, WeeklyReport
    from apps.ingest.models import DailyMetrics, IntradayDay
    from apps.planning.models import (
        PlannedWorkout, Race, StrengthSession, TrainingPlan, WorkoutAdjustment,
    )

    intraday = [f for f in _fields(IntradayDay) if f not in ("hr", "stress", "body_battery",
                                                              "steps")]
    return {
        "activities.csv": (Activity.objects.filter(athlete=athlete).order_by("started_at"),
                           [f for f in _fields(Activity) if f != "raw_file_id"]),
        "activity_metrics.csv": (ActivityMetrics.objects.filter(activity__athlete=athlete)
                                 .order_by("activity_id"), None),
        "laps.csv": (Segment.objects.filter(activity__athlete=athlete)
                     .order_by("activity_id", "index"), None),
        "run_reviews.csv": (RunReview.objects.filter(athlete=athlete).order_by("created_at"),
                            None),
        "daily_wellness.csv": (DailyMetrics.objects.filter(athlete=athlete)
                               .order_by("metric_date"), None),
        "intraday_daily.csv": (IntradayDay.objects.filter(athlete=athlete).order_by("day"),
                               intraday),
        "habits.csv": (HabitLog.objects.filter(athlete=athlete).order_by("at"), None),
        "cravings.csv": (CravingLog.objects.filter(athlete=athlete).order_by("at"), None),
        "mood.csv": (MoodLog.objects.filter(athlete=athlete).order_by("date"), None),
        "water.csv": (WaterLog.objects.filter(athlete=athlete).order_by("at"), None),
        "meals.csv": (Meal.objects.filter(athlete=athlete).order_by("eaten_at"), None),
        "weights.csv": (MetricEntry.objects.filter(athlete=athlete).order_by("recorded_at"),
                        None),
        "races.csv": (Race.objects.filter(athlete=athlete).order_by("date"), None),
        "plans.csv": (TrainingPlan.objects.filter(athlete=athlete).order_by("created_at"),
                      [f for f in _fields(TrainingPlan) if f != "chat_message_id"]),
        "workouts.csv": (PlannedWorkout.objects.filter(athlete=athlete).order_by("date", "id"),
                         None),
        "auto_adjustments.csv": (WorkoutAdjustment.objects.filter(athlete=athlete)
                                 .order_by("created_at"), None),
        "strength.csv": (StrengthSession.objects.filter(athlete=athlete).order_by("date"), None),
        "pain.csv": (PainReport.objects.filter(athlete=athlete).order_by("date"), None),
        "reports_weekly.csv": (WeeklyReport.objects.filter(athlete=athlete)
                               .order_by("week_start"), None),
        "reports_monthly.csv": (MonthlyReport.objects.filter(athlete=athlete)
                                .order_by("month"), None),
    }


README = """RunCoach data export ({date})

One CSV per table (UTF-8, comma-separated, first row = column names). Dates are
YYYY-MM-DD, times ISO 8601 (UTC unless the column says local). JSON-shaped cells
(workout steps, report payloads, intraday-derived values) are compact JSON.
athlete.json holds your profile and settings.

Not included: the original .fit files and meal photos (download those from Garmin
Connect / your phone), Garmin tokens and anything about other people.
"""


def athlete_json(athlete) -> dict:
    from .serializers import AthleteSerializer

    data = AthleteSerializer(athlete).data
    data["username"] = athlete.user.username
    data["email"] = athlete.user.email
    return json.loads(json.dumps(data, default=str))


def build_zip(athlete, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".part")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.txt", README.format(date=athlete.local_today.isoformat()))
        zf.writestr("athlete.json", json.dumps(athlete_json(athlete), indent=2))
        for name, (queryset, fields) in tables(athlete).items():
            zf.writestr(name, _csv(queryset, fields))
    partial.replace(path)
    return path.stat().st_size


def run_build(export_id: int) -> dict:
    export = DataExport.objects.select_related("athlete__user").filter(pk=export_id).first()
    if export is None:
        return {"skipped": "gone"}
    if export.status not in (DataExport.Status.PENDING, DataExport.Status.RUNNING):
        return {"skipped": export.status}
    export.status = DataExport.Status.RUNNING
    export.save(update_fields=["status"])
    name = f"{secrets.token_hex(16)}.zip"
    path = athlete_dir(export.athlete_id) / name
    try:
        size = build_zip(export.athlete, path)
    except Exception as exc:  # noqa: BLE001 — recorded on the row for the athlete
        logger.exception("export %s failed", export_id)
        export.status = DataExport.Status.FAILED
        export.error = "The export could not be built. Try again in an hour."[:300]
        export.finished_at = timezone.now()
        export.save(update_fields=["status", "error", "finished_at"])
        _unlink(path.with_suffix(".part"))
        return {"export": export_id, "error": type(exc).__name__}
    now = timezone.now()
    export.status = DataExport.Status.READY
    export.file_name = name
    export.size_bytes = size
    export.finished_at = now
    export.expires_at = now + VALID_FOR
    export.save(update_fields=["status", "file_name", "size_bytes", "finished_at",
                               "expires_at"])
    return {"export": export_id, "size": size}


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.exception("could not remove %s", path)


def file_path(export: DataExport) -> Path | None:
    if not export.file_name:
        return None
    return athlete_dir(export.athlete_id) / export.file_name


def cleanup(now: dt.datetime | None = None) -> int:
    """Expire ready exports past 24 h and delete their files."""
    now = now or timezone.now()
    done = 0
    for export in DataExport.objects.filter(status=DataExport.Status.READY, expires_at__lte=now):
        path = file_path(export)
        if path:
            _unlink(path)
        export.status = DataExport.Status.EXPIRED
        export.file_name = ""
        export.save(update_fields=["status", "file_name"])
        done += 1
    # Stuck builds (worker died) fail after a day so a new export is possible.
    DataExport.objects.filter(status__in=[DataExport.Status.PENDING, DataExport.Status.RUNNING],
                              created_at__lte=now - VALID_FOR).update(
        status=DataExport.Status.FAILED, error="The export did not finish.")
    return done


# --- views ----------------------------------------------------------------------------

def _queue(export_id: int) -> None:
    def send():
        try:
            from .tasks import build_export

            build_export.delay(export_id)
        except Exception:  # noqa: BLE001 — broker down: the row stays pending, retry later
            logger.warning("could not queue export %s", export_id)

    transaction.on_commit(send)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create(request):
    athlete = request.user.athlete
    now = timezone.now()
    with transaction.atomic():
        # Serialise per athlete so two quick clicks cannot both pass the hourly check.
        type(athlete).objects.select_for_update().filter(pk=athlete.pk).first()
        last = DataExport.objects.filter(athlete=athlete).order_by("-created_at").first()
        if last is not None and last.created_at > now - RATE_WINDOW:
            retry = int((last.created_at + RATE_WINDOW - now).total_seconds()) + 1
            return Response({"detail": "One export per hour — try again later.",
                             "retry_after_s": retry},
                            status=status.HTTP_429_TOO_MANY_REQUESTS,
                            headers={"Retry-After": str(retry)})
        export = DataExport.objects.create(athlete=athlete)
        _queue(export.pk)
    return Response(export_json(export), status=status.HTTP_202_ACCEPTED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def latest(request):
    export = DataExport.objects.filter(athlete=request.user.athlete).order_by("-created_at").first()
    return Response({"export": export_json(export) if export else None})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def download(request, pk: int):
    athlete = request.user.athlete
    not_found = Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)
    gone = Response({"detail": "This download link has been used or has expired — "
                               "make a new export."}, status=status.HTTP_410_GONE)
    with transaction.atomic():
        export = DataExport.objects.select_for_update().filter(athlete=athlete, pk=pk).first()
        token = request.query_params.get("token") or ""
        if export is None or not constant_time_compare(token, token_for(export)):
            return not_found
        if export.status != DataExport.Status.READY or (
                export.expires_at and export.expires_at <= timezone.now()):
            return gone
        path = file_path(export)
        if path is None or not path.exists():
            return gone
        handle = path.open("rb")
        export.status = DataExport.Status.DOWNLOADED
        export.downloaded_at = timezone.now()
        export.file_name = ""
        export.save(update_fields=["status", "downloaded_at", "file_name"])
    # The open handle keeps the bytes readable; the name is gone from disk at once.
    _unlink(path)
    filename = f"runcoach-export-{athlete.local_today.isoformat()}.zip"
    response = FileResponse(handle, as_attachment=True, filename=filename,
                            content_type="application/zip")
    response["Cache-Control"] = "no-store"
    return response
