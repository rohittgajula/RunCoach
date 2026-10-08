"""The pure packages (`analysis`, `planning`, `nutrition`) must never import Django.

This is the guard behind the claim that segmentation and the metrics engine are
testable without a database. Stated as a convention it lasts about a month; stated as
a test it holds. Each import runs in a subprocess with no DJANGO_SETTINGS_MODULE, so
a Django import fails loudly instead of quietly picking up ambient configuration.
"""

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent

PURE_MODULES = [
    "analysis",
    "analysis.segmentation",
    "analysis.running_truth",
    "analysis.heart_rate",
    "analysis.load",
    "analysis.fitness",
    "analysis.compliance",
    "analysis.insights",
    "analysis.dynamics",
    "analysis.habits",
    "analysis.progress",
    "analysis.weather_advice",
    # R10
    "analysis.zones",
    "analysis.sleep",
    "analysis.form",
    "analysis.records",
    "analysis.training_status",
    "analysis.gear",
    "analysis.body",
    "analysis.compare",
    "analysis.lung",
    "analysis.weekly_report",
    "analysis.achievements",
    "analysis.forecast",
    # R11
    "analysis.day",
    "analysis.day_trends",
    "analysis.route",
    # R12
    "analysis.buckets",
    "analysis.wake",
    # R13
    "analysis.injury",
    "analysis.run_review",
    "analysis.cravings",
    "analysis.caffeine",
    "analysis.monthly_report",
    "analysis.briefing",
    "planning.adapt",
    "planning.strength",
    "planning.garmin_strength",
    "planning.race_day",
    # R17
    "analysis.data_quality",
    "analysis.recovery_routine",
    "analysis.memory_facts",
    "analysis.garmin_deletions",
    "planning.illness",
    # R16
    "planning.edit",
    "analysis.freshness",
    # R14
    "analysis.heart_adaptation",
    "analysis.weather_plan",
    "analysis.experiments",
    "analysis.goals",
    "planning.ics",
    "planning",
    "planning.calendar",
    "planning.prediction",
    "planning.generator",
    "planning.readiness",
    "planning.workouts",
    "planning.baseline",
    "planning.adaptation",
    "planning.checkin",
    "planning.garmin_workout",
    "planning.reflow",
    "planning.relayout",
    "nutrition",
    "nutrition.targets",
    "nutrition.fueling",
    "nutrition.balance",
]


@pytest.mark.parametrize("module", PURE_MODULES)
def test_imports_without_django(module):
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONPATH": str(BACKEND)},
    )
    assert result.returncode == 0, (
        f"{module} cannot be imported without Django configured:\n{result.stderr}"
    )
