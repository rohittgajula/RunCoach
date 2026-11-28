"""R26 §3: the usage log — what it stores, and what it refuses to store.

This table is written to on every navigation, which makes it the one table in the
app that an ordinary bug can fill. So most of these tests are about the caps and
the validation, not about counting.

The other thing asserted here is the narrowness of what it can hold: keys from a
fixed charset and a timestamp. If it ever becomes possible to post free text
through this endpoint, a log that was only ever meant to answer "which screens do
I open" starts holding things nobody agreed to store.
"""

from __future__ import annotations

import datetime as dt

from django.utils import timezone

from apps.athletes import usage
from apps.athletes.models import ScreenView

POST = "/api/usage/"
SUMMARY = "/api/usage/summary/"


def ev(key="/today", kind="section", at=None):
    out = {"key": key, "kind": kind}
    if at is not None:
        out["at"] = at.isoformat()
    return out


def send(api, *events):
    return api.post(POST, {"events": list(events)}, format="json")


# --- what it stores ----------------------------------------------------------

def test_a_batch_is_stored(api, athlete):
    res = send(api, ev("/today"), ev("/plan"), ev("weight", "card"))
    assert res.status_code == 202
    assert res.data["stored"] == 3
    assert ScreenView.objects.filter(athlete=athlete).count() == 3


def test_the_local_date_is_his_not_utcs(api, athlete):
    """At 00:30 in Kolkata, UTC is still yesterday. Counting "days seen" in UTC
    would split one of his evenings across two days."""
    at = timezone.now().replace(hour=19, minute=30)   # 01:00 next day in Kolkata
    send(api, ev("/today", at=at))
    row = ScreenView.objects.get(athlete=athlete)
    assert row.local_date == usage._local_date(athlete, row.at)


def test_keys_are_lowercased_and_trimmed(api, athlete):
    send(api, ev("  /Health/Day  "))
    assert ScreenView.objects.get(athlete=athlete).key == "/health/day"


# --- what it refuses ---------------------------------------------------------

def test_free_text_cannot_be_posted_through_it(api, athlete):
    """The guard that matters: this endpoint must not become a place arbitrary
    strings end up."""
    res = send(api, ev("ferritin was 18 and I am worried about it"))
    assert res.status_code == 400
    assert not ScreenView.objects.exists()


def test_a_key_with_markup_or_a_url_is_refused(api, athlete):
    for bad in ("<script>x</script>", "https://example.com/?q=1", "a key with spaces",
                "KEY_WITH_$IGNS", "../../etc/passwd"):
        assert send(api, ev(bad)).status_code == 400, bad
    assert not ScreenView.objects.exists()


def test_an_unknown_kind_is_refused(api, athlete):
    assert send(api, ev("/today", kind="whatever")).status_code == 400


def test_an_overlong_key_is_refused(api, athlete):
    assert send(api, ev("/" + "a" * 100)).status_code == 400


def test_an_oversized_batch_is_truncated_rather_than_rejected(api, athlete):
    """A 400 here would make a looping client retry the same oversized batch
    forever. Losing the tail is the cheaper failure."""
    res = send(api, *[ev(f"/x{i}") for i in range(usage.MAX_BATCH + 25)])
    assert res.status_code == 202
    assert res.data["stored"] == usage.MAX_BATCH


def test_the_daily_cap_stops_a_navigation_loop_filling_the_table(api, athlete):
    today = athlete.local_today
    ScreenView.objects.bulk_create([
        ScreenView(athlete=athlete, key="/today", kind="section",
                   at=timezone.now(), local_date=today)
        for _ in range(usage.MAX_PER_DAY)
    ])
    res = send(api, ev("/plan"))
    assert res.status_code == 202
    assert res.data["stored"] == 0 and res.data["reason"] == "daily cap"
    assert ScreenView.objects.filter(athlete=athlete).count() == usage.MAX_PER_DAY


def test_the_cap_is_per_day_so_tomorrow_works_again(api, athlete):
    yesterday = athlete.local_today - dt.timedelta(days=1)
    ScreenView.objects.bulk_create([
        ScreenView(athlete=athlete, key="/today", kind="section",
                   at=timezone.now(), local_date=yesterday)
        for _ in range(usage.MAX_PER_DAY)
    ])
    assert send(api, ev("/plan")).data["stored"] == 1


# --- timestamps --------------------------------------------------------------

def test_a_timestamp_from_the_future_is_corrected_not_trusted(api, athlete):
    send(api, ev("/today", at=timezone.now() + dt.timedelta(days=400)))
    row = ScreenView.objects.get(athlete=athlete)
    assert row.at <= timezone.now() + dt.timedelta(minutes=5)


def test_a_timestamp_from_too_long_ago_is_corrected(api, athlete):
    send(api, ev("/today", at=timezone.now() - dt.timedelta(days=90)))
    row = ScreenView.objects.get(athlete=athlete)
    assert row.at > timezone.now() - usage.MAX_BACKDATE


def test_a_plausible_offline_backlog_keeps_its_own_times(api, athlete):
    """A phone that was offline for a day must not have its whole backlog
    collapsed onto the moment it reconnected."""
    at = timezone.now() - dt.timedelta(hours=20)
    send(api, ev("/today", at=at))
    assert abs((ScreenView.objects.get(athlete=athlete).at - at).total_seconds()) < 2


def test_an_event_with_no_time_is_stamped_now(api, athlete):
    send(api, {"key": "/today", "kind": "section"})
    assert ScreenView.objects.filter(athlete=athlete).count() == 1


# --- pruning -----------------------------------------------------------------

def test_old_rows_are_deleted_on_write(api, athlete):
    old = athlete.local_today - dt.timedelta(days=usage.RETAIN_DAYS + 5)
    ScreenView.objects.create(athlete=athlete, key="/old", kind="section",
                              at=timezone.now(), local_date=old)
    send(api, ev("/today"))
    assert not ScreenView.objects.filter(key="/old").exists()
    assert ScreenView.objects.filter(key="/today").exists()


def test_rows_inside_the_window_are_kept(api, athlete):
    recent = athlete.local_today - dt.timedelta(days=usage.RETAIN_DAYS - 5)
    ScreenView.objects.create(athlete=athlete, key="/keep", kind="section",
                              at=timezone.now(), local_date=recent)
    send(api, ev("/today"))
    assert ScreenView.objects.filter(key="/keep").exists()


# --- the summary -------------------------------------------------------------

def test_an_empty_summary_is_honest(api, athlete):
    body = api.get(SUMMARY).json()
    assert body["rows"] == [] and body["total_views"] == 0
    assert body["days"] == usage.DEFAULT_DAYS
    assert "Never what was on them" in body["note"]


def test_days_seen_is_distinct_days_not_total_opens(api, athlete):
    """The distinction the whole screen rests on: forty opens in one sitting is a
    screen he bounced off, not a screen he uses."""
    today = athlete.local_today
    ScreenView.objects.bulk_create([
        ScreenView(athlete=athlete, key="/bounced", kind="section",
                   at=timezone.now(), local_date=today) for _ in range(40)
    ] + [
        ScreenView(athlete=athlete, key="/daily", kind="section", at=timezone.now(),
                   local_date=today - dt.timedelta(days=i)) for i in range(5)
    ])
    rows = {r["key"]: r for r in api.get(SUMMARY).json()["rows"]}
    assert rows["/bounced"]["views"] == 40 and rows["/bounced"]["days_seen"] == 1
    assert rows["/daily"]["views"] == 5 and rows["/daily"]["days_seen"] == 5
    # And the one used daily is listed first, despite having 8x fewer opens.
    assert api.get(SUMMARY).json()["rows"][0]["key"] == "/daily"


def test_the_window_excludes_what_falls_outside_it(api, athlete):
    old = athlete.local_today - dt.timedelta(days=20)
    ScreenView.objects.create(athlete=athlete, key="/old", kind="section",
                              at=timezone.now(), local_date=old)
    assert api.get(f"{SUMMARY}?days=7").json()["rows"] == []
    assert api.get(f"{SUMMARY}?days=30").json()["rows"][0]["key"] == "/old"


def test_a_silly_window_is_clamped_not_an_error(api, athlete):
    assert api.get(f"{SUMMARY}?days=100000").json()["days"] == usage.MAX_DAYS
    assert api.get(f"{SUMMARY}?days=0").json()["days"] == 1
    assert api.get(f"{SUMMARY}?days=nonsense").json()["days"] == usage.DEFAULT_DAYS


# --- tenancy -----------------------------------------------------------------

def test_another_athletes_usage_is_invisible(api, athlete, django_user_model):
    from apps.athletes.models import Athlete

    other = Athlete.objects.create(
        user=django_user_model.objects.create_user("other2", password="correct-horse-3"),
        display_name="Other", timezone="Asia/Kolkata",
    )
    ScreenView.objects.create(athlete=other, key="/theirs", kind="section",
                              at=timezone.now(), local_date=other.local_today)
    assert api.get(SUMMARY).json()["rows"] == []


def test_it_needs_a_login(client):
    assert client.post(POST, {"events": []}, content_type="application/json").status_code in (401, 403)
    assert client.get(SUMMARY).status_code in (401, 403)
