"""R13 §15: data export build and cleanup (metrics queue)."""

from __future__ import annotations

from celery import shared_task


@shared_task(name="athletes.build_export")
def build_export(export_id: int) -> dict:
    from .export import run_build

    return run_build(export_id)


@shared_task(name="athletes.export_cleanup")
def export_cleanup() -> dict:
    from .export import cleanup

    return {"expired": cleanup()}
