"""R14 pure modules: heart adaptation (synthetic record streams), weather ratings and
rescheduling, ICS, experiments, goals. No database, no network."""

import datetime as dt

import pytest

from analysis import experiments as ex
from analysis import goals as gl
from analysis import heart_adaptation as ha
from analysis import weather_plan as wp
from planning import ics

PACE_600 = 1000 / 600          # m/s at 10:00/km


# --- synthetic runs -----------------------------------------------------------------------

def stream(parts, *, start_alt=None, climb_per_m=0.0, step=1.0):
    """parts: [(kind, seconds, speed m/s or fn(t), hr int or fn(t) or None)].
    Returns (points, blocks) sampled every `step` seconds."""
    points, blocks, t, dist = [], [], 0.0, 0.0
    for kind, seconds, speed, hr in parts:
        blocks.append(ha.Block(kind, t, seconds))
        local = 0.0
        while local < seconds:
            s = speed(local) if callable(speed) else speed
            h = hr(local) if callable(hr) else hr
            alt = None if start_alt is None else start_alt + dist * climb_per_m
            points.append(ha.Point(t + local, None if h is None else int(round(h)), s, alt))
            dist += (s or 0) * step
            local += step
        t += seconds
    return points, blocks


def easy_run(minutes=30, hr=145, speed=PACE_600, warmup_hr=None):
    parts = []
    if warmup_hr is not None:
        parts.append(("run", 300, speed, warmup_hr))
        minutes -= 5
    parts.append(("run", minutes * 60, speed, hr))
    return stream(parts)


def analyse(points, blocks, **kw):
    kw.setdefault("ref_hr", 150)
    kw.setdefault("ref_pace", 600)
    return ha.analyse_run(points, blocks, **kw)


class TestHeartPerRun:
    def test_hr_at_reference_pace_and_pace_at_reference_hr(self):
        r = analyse(*easy_run(hr=145), ref_hr=145)
        assert r["hr_at_ref_pace"] == 145
        assert r["pace_at_ref_hr"] == 600
        assert r["run_s"] == 1800 and r["steady_s"] >= 1400
        assert r["distance_km"] == pytest.approx(3.0, abs=0.02)

    def test_no_match_outside_the_bands(self):
        r = analyse(*easy_run(hr=145), ref_hr=150, ref_pace=540)
        assert r["pace_at_ref_hr"] is None           # 145 is outside 150 ± 3
        assert r["hr_at_ref_pace"] is None           # 10:00/km is outside 9:00 ± 15 s

    def test_warm_up_is_left_out(self):
        r = analyse(*easy_run(hr=145, warmup_hr=170))
        assert r["hr_at_ref_pace"] == 145

    def test_first_minute_of_each_block_is_left_out(self):
        points, blocks = stream([("run", 400, PACE_600, 145), ("walk", 120, 1.2, 120),
                                 ("run", 400, PACE_600, lambda t: 175 if t < 60 else 146)])
        r = analyse(points, blocks)
        assert r["hr_at_ref_pace"] in (145, 146)

    def test_unsteady_pace_gives_no_steady_running(self):
        points, blocks = stream([("run", 1800, lambda t: PACE_600 * (1.3 if int(t) % 2 else 0.7),
                                  145)])
        r = analyse(points, blocks)
        assert r["steady_s"] == 0
        assert r["hr_at_ref_pace"] is None and r["efficiency"] is None
        assert r["decoupling_pct"] is None

    def test_walking_pace_is_not_steady_running(self):
        points, blocks = stream([("run", 1800, 1.2, 120)])
        assert analyse(points, blocks)["steady_s"] == 0

    def test_efficiency_is_metres_per_minute_per_beat(self):
        r = analyse(*easy_run(hr=150))
        assert r["efficiency"] == pytest.approx(PACE_600 * 60 / 150, abs=0.002)
        assert r["efficiency_adj"] == pytest.approx(r["efficiency"], abs=0.002)

    def test_decoupling_from_rising_heart_rate(self):
        points, blocks = stream([("run", 2400, PACE_600, lambda t: 140 + 14 * t / 2400)])
        r = analyse(points, blocks)
        # Steady part is 300–2400 s: first-half mean ≈ 143.6, second ≈ 149.7 → ≈ 4 %.
        assert 3.0 <= r["decoupling_pct"] <= 5.0
        flat = analyse(*easy_run(minutes=40, hr=145))
        assert flat["decoupling_pct"] == 0.0

    def test_decoupling_needs_ten_minutes_of_steady_running(self):
        r = analyse(*easy_run(minutes=12, hr=145))
        assert r["steady_s"] < 600 and r["decoupling_pct"] is None

    def test_hr_recovery_after_a_run_block(self):
        points, blocks = stream([
            ("run", 300, PACE_600, 160),
            ("walk", 120, 1.2, lambda t: max(130, 160 - 0.5 * t)),
            ("run", 300, PACE_600, 162),
            ("walk", 120, 1.2, lambda t: max(140, 162 - t * 22 / 60)),
        ])
        r = analyse(points, blocks)
        assert r["hr_recovery_bpm"] == 26           # median of 30 and 22
        assert r["hr_recovery_end_bpm"] == 22

    def test_no_recovery_without_a_walk_after(self):
        r = analyse(*easy_run(hr=150))
        assert r["hr_recovery_bpm"] is None and r["hr_recovery_end_bpm"] is None

    def test_short_walk_does_not_count_as_recovery(self):
        points, blocks = stream([("run", 300, PACE_600, 160), ("walk", 30, 1.2, 150),
                                 ("run", 300, PACE_600, 160)])
        assert analyse(points, blocks)["hr_recovery_bpm"] is None

    def test_time_to_settle(self):
        points, blocks = stream([("run", 600, PACE_600, lambda t: min(150, 120 + t / 3))])
        r = analyse(points, blocks)
        # HR reaches 144 (within 6 of the plateau) at 72 s.
        assert 66 <= r["settle_s"] <= 80

    def test_never_settles(self):
        points, blocks = stream([("run", 600, PACE_600, lambda t: 120 + t / 5)])
        assert analyse(points, blocks)["settle_s"] is None

    def test_longest_run_under_the_cap(self):
        points, blocks = stream([
            ("run", 300, PACE_600, 145),                         # 5 min under 150
            ("walk", 120, 1.2, 125),
            ("run", 900, PACE_600, lambda t: 148 if t < 660 else 158),   # 11 min, then over
        ])
        r = analyse(points, blocks, ref_hr=150)
        assert 650 <= r["duration_under_cap_s"] <= 670

    def test_a_brief_spike_does_not_end_the_stretch(self):
        points, blocks = stream([("run", 600, PACE_600,
                                  lambda t: 165 if 200 <= t < 202 else 145)])
        assert analyse(points, blocks)["duration_under_cap_s"] >= 595

    def test_walk_break_ends_the_stretch(self):
        points, blocks = stream([("run", 300, PACE_600, 140), ("walk", 60, 1.2, 120),
                                 ("run", 400, PACE_600, 140)])
        assert 395 <= analyse(points, blocks)["duration_under_cap_s"] <= 400

    def test_heat_is_flagged_and_adjusted(self):
        r = analyse(*easy_run(hr=150), feels_like=32.0)
        assert r["hot"] is True and "hot" in r["flags"]
        assert r["hr_at_ref_pace"] == 150 and r["hr_at_ref_pace_adj"] == 138
        assert r["efficiency_adj"] > r["efficiency"]
        cool = analyse(*easy_run(hr=150), feels_like=18.0)
        assert cool["hot"] is False and cool["hr_at_ref_pace_adj"] == 150
        assert analyse(*easy_run(hr=150))["hot"] is None

    def test_hills_are_flagged_and_normalised(self):
        flat_points, blocks = stream([("run", 1800, PACE_600, 150)], start_alt=100.0)
        flat = analyse(flat_points, blocks)
        assert flat["elev_gain_per_km"] == 0.0 and flat["hilly"] is False
        points, blocks = stream([("run", 1800, PACE_600, 150)], start_alt=100.0,
                                climb_per_m=0.03)
        hill = analyse(points, blocks)
        assert hill["elev_gain_per_km"] == pytest.approx(30, abs=2)
        assert hill["hilly"] is True and "hilly" in hill["flags"]
        assert hill["efficiency_adj"] > hill["efficiency"]
        assert analyse(*easy_run())["elev_gain_per_km"] is None      # no altitude at all

    def test_no_heart_rate(self):
        points, blocks = stream([("run", 1800, PACE_600, None)])
        r = analyse(points, blocks)
        assert "no_hr" in r["flags"] and r["duration_under_cap_s"] == 0
        assert r["hr_at_ref_pace"] is None and r["pace_at_ref_hr"] is None

    def test_sparse_sampling_still_works(self):
        points, blocks = stream([("run", 1800, PACE_600, 145)], step=4.0)
        r = analyse(points, blocks, ref_hr=145)
        assert r["hr_at_ref_pace"] == 145 and r["pace_at_ref_hr"] == 600

    def test_short_run_flag(self):
        assert "short" in analyse(*easy_run(minutes=8))["flags"]

    def test_points_out_of_order_are_sorted(self):
        points, blocks = easy_run(hr=145)
        assert analyse(list(reversed(points)), blocks)["hr_at_ref_pace"] == 145


def run_row(i, day, **values):
    base = {"activity_id": i, "date": day, "flags": [], "hot": False,
            "hr_at_ref_pace": None, "pace_at_ref_hr": None, "efficiency": None,
            "decoupling_pct": None, "duration_under_cap_s": 0}
    return {**base, **values}


class TestHeartAcrossRuns:
    def runs(self):
        start = dt.date(2026, 3, 12)
        rows = []
        for i in range(10):
            rows.append(run_row(i, start + dt.timedelta(days=3 * i),
                                duration_under_cap_s=300 + 40 * i,
                                hr_at_ref_pace=158 - i, pace_at_ref_hr=700 - 5 * i,
                                efficiency=1.0 + i / 100, decoupling_pct=8 - i / 2))
        return rows

    def test_rolling_trend_needs_three_runs(self):
        trend = ha.rolling_trend(self.runs())
        assert trend[0]["hr_at_ref_pace"] is None and trend[1]["hr_at_ref_pace"] is None
        assert trend[2]["hr_at_ref_pace"] == 157               # median of 158, 157, 156
        assert trend[9]["duration_under_cap_s"] == 300 + 40 * 6   # median of runs 3..9

    def test_since_day_one_in_plain_sentences(self):
        day1 = ha.since_day1(self.runs(), ref_hr=150, ref_pace=600)
        assert day1["first"]["duration_under_cap_s"] == 340
        assert day1["latest"]["duration_under_cap_s"] == 620
        first, pace, speed = day1["sentences"]
        assert first == "Day 1 (12 Mar): 5.7 min of running at or under 150 bpm. Now: 10 min."
        assert pace == ("At the same pace (10:00/km) your heart rate is 7 bpm lower than in "
                        "your first runs.")
        assert speed == "At 150 bpm you now run 0:35 per km faster than at first."
        assert not any("because" in s or "improv" in s for s in day1["sentences"])

    def test_since_day_one_needs_four_runs(self):
        assert ha.since_day1(self.runs()[:3], ref_hr=150, ref_pace=600) is None
        assert ha.since_day1(self.runs()[:4], ref_hr=150, ref_pace=600) is not None

    def test_runs_without_heart_rate_are_left_out(self):
        rows = self.runs()
        rows[0] = {**rows[0], "flags": ["no_hr"], "duration_under_cap_s": 0}
        assert ha.since_day1(rows, ref_hr=150, ref_pace=600)["first"]["date"] == rows[1]["date"]

    def test_heat_view(self):
        rows = self.runs()
        for i, row in enumerate(rows):
            row["hot"] = i % 2 == 0
            if row["hot"]:
                row["hr_at_ref_pace"] += 6
        view = ha.heat_view(rows)
        assert view["hot_runs"] == 5 and view["cool_runs"] == 5
        assert view["hot_vs_cool"]["diff"] > 0
        assert view["adaptation"]["recent_hot_avg"] < view["adaptation"]["early_hot_avg"]
        assert "lower heart rate" in view["sentence"]

    def test_key_numbers(self):
        rows = self.runs()
        trend = ha.rolling_trend(rows)
        first = ha.snapshot(rows[:3])
        numbers = {n["key"]: n for n in ha.key_numbers(trend, first, 150)}
        assert numbers["duration_under_cap"]["better"] is True
        assert numbers["hr_at_ref_pace"]["better"] is True
        assert numbers["hr_at_ref_pace"]["change"] < 0
        assert numbers["pace_at_ref_hr"]["display"].endswith("/km")
        assert all(n["info"] for n in numbers.values())

    def test_headline(self):
        assert ha.headline(None, [], 150).startswith("No runs")
        assert "2 runs so far" in ha.headline(None, [{}, {}], 150)


# --- weather ------------------------------------------------------------------------------

def hour(day, h, feels=25.0, rain=0, aqi=40, code=1):
    return {"time": f"{day.isoformat()}T{h:02d}:00", "feels_like": feels, "temp": feels,
            "precip_prob": rain, "aqi": aqi, "weather_code": code, "condition": "Clear"}


def day_hours(day, feels=25.0, **kw):
    return [hour(day, h, feels=feels, **kw) for h in range(24)]


class TestWeatherRatings:
    def test_hour_rating_thresholds(self):
        d = dt.date(2026, 10, 8)
        assert wp.hour_rating(hour(d, 6, feels=22)) == "good"
        assert wp.hour_rating(hour(d, 6, feels=27)) == "ok"
        assert wp.hour_rating(hour(d, 6, feels=31)) == "poor"
        assert wp.hour_rating(hour(d, 6, feels=34)) == "bad"
        assert wp.hour_rating(hour(d, 6, rain=70)) == "bad"
        assert wp.hour_rating(hour(d, 6, aqi=151)) == "bad"
        assert wp.hour_rating(hour(d, 6, aqi=150)) == "poor"
        assert wp.hour_rating(hour(d, 6, code=95)) == "bad"
        assert wp.hour_rating({"time": "2026-10-08T06:00"}) is None

    def test_a_day_is_bad_only_when_every_window_is(self):
        d = dt.date(2026, 10, 8)
        hot = day_hours(d, feels=36)
        check = wp.check_day(hot, d)
        assert check.verdict == "bad" and check.reasons[0]["key"] == "heat"
        assert "feels like 36 °C" in check.reasons[0]["text"]
        one_ok = [hour(d, h, feels=36 if h != 6 else 29) for h in range(24)]
        assert wp.check_day(one_ok, d).verdict == "good"
        warm = [hour(d, h, feels=36 if h != 6 else 31) for h in range(24)]
        assert wp.check_day(warm, d).verdict == "caution"
        assert wp.check_day([], d).verdict is None

    def test_storm_and_air_reasons(self):
        d = dt.date(2026, 10, 8)
        check = wp.check_day(day_hours(d, code=95, aqi=180), d)
        assert {r["key"] for r in check.reasons} == {"storm", "air"}

    def test_aqi_and_uv_levels(self):
        assert wp.aqi_level(42) == ("good", "Good — fine for any run.")
        assert wp.aqi_level(160)[0] == "unhealthy"
        assert wp.aqi_level(None) == (None, None)
        assert wp.uv_level(7) == "high" and wp.uv_level(None) is None

    def test_best_windows_one_per_day(self):
        now = dt.datetime(2026, 10, 8, 4, 30)
        hours = day_hours(dt.date(2026, 10, 8), feels=30) + day_hours(dt.date(2026, 10, 9),
                                                                      feels=30)
        hours[6]["feels_like"] = 24
        windows = wp.best_windows(hours, now)
        assert [w["date"] for w in windows] == ["2026-10-08", "2026-10-09"]
        assert windows[0]["start"] == "2026-10-08T06:00"


TODAY = dt.date(2026, 10, 7)          # a Wednesday
ALL_DAYS = set(range(7))


def checks_for(bad_days, start=TODAY, days=7, good_feels=25.0):
    hourly = []
    for i in range(days):
        day = start + dt.timedelta(days=i)
        hourly += day_hours(day, feels=36 if day in bad_days else good_feels)
    return {start + dt.timedelta(days=i): wp.check_day(hourly, start + dt.timedelta(days=i))
            for i in range(days)}


def S(i, day_offset, kind="EASY", status="planned"):
    return wp.Session(i, TODAY + dt.timedelta(days=day_offset), kind, status)


class TestWeatherReschedule:
    def test_moves_a_run_off_a_bad_day(self):
        thu = TODAY + dt.timedelta(days=1)
        sessions = [S(1, 1), S(2, 3, "LONG")]
        out = wp.propose(sessions, checks_for({thu}), today=TODAY, available=ALL_DAYS)
        assert len(out) == 1
        p = out[0]
        assert (p.workout_id, p.from_date, p.action) == (1, thu, "move")
        assert p.to_date == TODAY + dt.timedelta(days=2)       # Friday, the nearest free day
        assert p.reasons[0]["key"] == "heat"

    def test_never_today_past_completed_or_races(self):
        checks = checks_for({TODAY, TODAY + dt.timedelta(days=1)})
        sessions = [S(1, 0), S(2, 1, status="completed"), S(3, 1, "RACE"), S(4, -1)]
        assert wp.propose(sessions, checks, today=TODAY, available=ALL_DAYS) == []

    def test_only_the_next_three_days(self):
        day4 = TODAY + dt.timedelta(days=4)
        assert wp.propose([S(1, 4)], checks_for({day4}), today=TODAY, available=ALL_DAYS) == []

    def test_same_week_only_and_available_days_only(self):
        sat = TODAY + dt.timedelta(days=3)
        # Fri is the only other free day this week but not available; Sun is free.
        sessions = [S(1, 3)]
        out = wp.propose(sessions, checks_for({sat}), today=TODAY,
                         available=ALL_DAYS - {4, 3})
        assert [p.to_date for p in out] == [TODAY + dt.timedelta(days=4)]   # Sunday
        assert wp.propose(sessions, checks_for({sat}), today=TODAY,
                          available={5}) == []                 # only Saturday itself

    def test_long_run_keeps_its_spacing(self):
        fri = TODAY + dt.timedelta(days=2)
        # LONG on Fri (bad). Thu has a tempo, Sat is free but Sun has intervals: only
        # a day not next to either may take it — none in this week after today.
        sessions = [S(1, 1, "TEMPO"), S(2, 2, "LONG"), S(3, 4, "INTERVALS")]
        assert wp.propose(sessions, checks_for({fri}), today=TODAY, available=ALL_DAYS) == []
        # Without the Sunday intervals, Sun is fine (Sat would sit next to nothing hard
        # either, but it is nearer: Sat).
        out = wp.propose(sessions[:2], checks_for({fri}), today=TODAY, available=ALL_DAYS)
        assert [p.to_date for p in out] == [TODAY + dt.timedelta(days=3)]

    def test_nothing_lands_on_the_day_before_a_race(self):
        thu = TODAY + dt.timedelta(days=1)
        sessions = [S(1, 1), S(2, 2), S(3, 4, "RACE")]           # race Sunday
        out = wp.propose(sessions, checks_for({thu}), today=TODAY, available=ALL_DAYS)
        assert out == []          # Fri has a run, Sat is the day before the race
        out = wp.propose(sessions, checks_for({thu}), today=TODAY, available=ALL_DAYS,
                         last_date=TODAY + dt.timedelta(days=3))
        assert out == []

    def test_swaps_with_an_optional_walk(self):
        thu = TODAY + dt.timedelta(days=1)
        sessions = [S(1, 1), S(2, 2, "WALK")]
        [p] = wp.propose(sessions, checks_for({thu}), today=TODAY, available=ALL_DAYS)
        assert p.action == "swap" and p.swap_with == 2 and p.to_date == thu + dt.timedelta(days=1)

    def test_target_must_be_better(self):
        thu, fri, sat, sun = (TODAY + dt.timedelta(days=i) for i in (1, 2, 3, 4))
        assert wp.propose([S(1, 1)], checks_for({thu, fri, sat, sun}), today=TODAY,
                          available=ALL_DAYS) == []

    def test_two_bad_runs_do_not_take_the_same_day(self):
        thu, fri = TODAY + dt.timedelta(days=1), TODAY + dt.timedelta(days=2)
        out = wp.propose([S(1, 1), S(2, 2)], checks_for({thu, fri}), today=TODAY,
                         available=ALL_DAYS)
        assert len({p.to_date for p in out}) == len(out) == 2

    def test_skip_list(self):
        thu = TODAY + dt.timedelta(days=1)
        assert wp.propose([S(1, 1)], checks_for({thu}), today=TODAY, available=ALL_DAYS,
                          skip={(1, thu)}) == []

    def test_text(self):
        assert wp.text_for("LONG", dt.date(2026, 10, 8), dt.date(2026, 10, 9)) == \
            "Weather: move Thu long run to Fri?"


# --- ICS ----------------------------------------------------------------------------------

class TestIcs:
    def test_escape_and_fold(self):
        assert ics.escape("a,b;c\\d\ne") == "a\\,b\\;c\\\\d\\ne"
        line = "DESCRIPTION:" + "🏃 Run 4:30 · easy, " * 20
        folded = ics.fold(line)
        parts = folded.split("\r\n")
        assert all(len(p.encode()) <= 75 for p in parts)
        assert all(p.startswith(" ") for p in parts[1:])
        assert "".join([parts[0]] + [p[1:] for p in parts[1:]]) == line

    def test_calendar_shape(self):
        stamp = dt.datetime(2026, 10, 7, 10, 0, tzinfo=dt.timezone.utc)
        allday = ics.Event(uid="workout-1@runcoach", summary="Easy run · 30 min",
                           description="Run 4:30\nWalk 30s", day=dt.date(2026, 10, 9))
        race = ics.Event(uid="race-2@runcoach", summary="10K", description="Race",
                         start_utc=dt.datetime(2026, 11, 8, 1, 0, tzinfo=dt.timezone.utc),
                         duration_s=4200)
        body = ics.calendar([(allday, 0, stamp), (race, 3, stamp)], name="RunCoach", stamp=stamp)
        assert body.startswith("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n")
        assert body.endswith("END:VCALENDAR\r\n")
        assert "\n" not in body.replace("\r\n", "")
        assert "DTSTART;VALUE=DATE:20261009\r\nDTEND;VALUE=DATE:20261010" in body
        assert "DTSTART:20261108T010000Z\r\nDTEND:20261108T021000Z" in body
        assert "SEQUENCE:3" in body and "UID:workout-1@runcoach" in body
        assert "DESCRIPTION:Run 4:30\\nWalk 30s" in body
        assert "DTSTAMP:20261007T100000Z" in body

    def test_content_hash_tracks_changes(self):
        a = ics.Event(uid="u", summary="Easy", description="x", day=dt.date(2026, 10, 9))
        assert a.content_hash() == ics.Event(uid="u", summary="Easy", description="x",
                                             day=dt.date(2026, 10, 9)).content_hash()
        assert a.content_hash() != ics.Event(uid="u", summary="Easy", description="x",
                                             day=dt.date(2026, 10, 10)).content_hash()

    def test_steps_text(self):
        steps = [{"label": "Walk warm-up", "duration_s": 120},
                 {"label": "Run 4:30", "duration_s": 270, "hr_min": 130, "hr_max": 145},
                 {"label": "Run 4:30", "duration_s": 270, "hr_min": 130, "hr_max": 145}]
        assert ics.steps_text(steps) == "Walk warm-up · 2 min\n2 × Run 4:30 (HR 130–145)"
        assert ics.minutes(5400) == "1 h 30 min"


# --- experiments ----------------------------------------------------------------------------

D0 = dt.date(2026, 10, 1)


def days(n):
    return [D0 + dt.timedelta(days=i) for i in range(n)]


class TestExperiments:
    def test_no_alcohol_adherence(self):
        logs = {D0 + dt.timedelta(days=2): ex.DayLog(habit=2)}
        today = D0 + dt.timedelta(days=5)
        a = ex.adherence("no_alcohol", {"habit": "alcohol", "max_per_day": 0}, D0,
                         D0 + dt.timedelta(days=20), today, logs)
        assert a["days_counted"] == 5 and a["days_kept"] == 4 and a["pct"] == 80
        assert a["today"] is None                      # today isn't over and nothing logged
        assert a["series"][2]["kept"] is False and a["series"][2]["display"] == "2 drinks"
        logs[today] = ex.DayLog(habit=1)
        a = ex.adherence("no_alcohol", {"habit": "alcohol", "max_per_day": 0}, D0,
                         D0 + dt.timedelta(days=20), today, logs)
        assert a["today"] is False

    def test_late_caffeine_counts_only_after_the_cutoff(self):
        rule = {"habit": "caffeine", "max_per_day": 0, "after": "14:00"}
        logs = {D0: ex.DayLog(habit=3, habit_late=0), D0 + dt.timedelta(days=1):
                ex.DayLog(habit=1, habit_late=1)}
        a = ex.adherence("no_late_caffeine", rule, D0, D0 + dt.timedelta(days=13),
                         D0 + dt.timedelta(days=2), logs)
        assert [d["kept"] for d in a["series"][:2]] == [True, False]

    def test_bedtime(self):
        rule = {"bedtime": "22:30"}
        logs = {D0: ex.DayLog(bedtime=dt.datetime(2026, 10, 1, 22, 10)),
                D0 + dt.timedelta(days=1): ex.DayLog(bedtime=dt.datetime(2026, 10, 2, 23, 5)),
                D0 + dt.timedelta(days=2): ex.DayLog(bedtime=dt.datetime(2026, 10, 4, 0, 40))}
        a = ex.adherence("bed_by", rule, D0, D0 + dt.timedelta(days=13),
                         D0 + dt.timedelta(days=4), logs)
        assert [d["kept"] for d in a["series"]] == [True, False, False, None, None]
        assert a["series"][2]["display"] == "00:40"
        assert ex.bed_date(dt.datetime(2026, 10, 4, 0, 40)) == dt.date(2026, 10, 3)

    def test_steps(self):
        rule = {"min_steps": 10000}
        today = D0 + dt.timedelta(days=2)
        logs = {D0: ex.DayLog(steps=12000), D0 + dt.timedelta(days=1): ex.DayLog(steps=8000),
                today: ex.DayLog(steps=10500)}
        a = ex.adherence("steps", rule, D0, D0 + dt.timedelta(days=13), today, logs)
        assert [d["kept"] for d in a["series"]] == [True, False, True]
        assert a["series"][0]["display"] == "12,000 steps"

    def test_compare_before_and_during(self):
        base = (D0 - dt.timedelta(days=14), D0 - dt.timedelta(days=1))
        during = (D0, D0 + dt.timedelta(days=13))
        hrv = {**{base[0] + dt.timedelta(days=i): 45 for i in range(14)},
               **{D0 + dt.timedelta(days=i): 52 for i in range(14)}}
        rhr = {**{base[0] + dt.timedelta(days=i): 60 for i in range(14)},
               **{D0 + dt.timedelta(days=i): 61 for i in range(14)}}
        mood = {D0: 4, D0 + dt.timedelta(days=1): 4}
        metrics = {m["key"]: m for m in ex.compare({"hrv": hrv, "rhr": rhr, "mood": mood},
                                                   base, during)}
        assert metrics["hrv"]["direction"] == "better" and metrics["hrv"]["diff"] == 7
        assert metrics["hrv"]["n_before"] == metrics["hrv"]["n_during"] == 14
        assert metrics["rhr"]["direction"] == "no_clear_difference"
        assert metrics["mood"]["enough_data"] is False and metrics["mood"]["direction"] is None
        assert "not enough data" in metrics["mood"]["sentence"]
        assert "because" not in metrics["hrv"]["sentence"]
        assert "HRV" in ex.summary("No alcohol", 90, list(metrics.values()), True)

    def test_caveat_is_non_causal(self):
        assert "not that it caused" in ex.CAVEAT


# --- goals ------------------------------------------------------------------------------------

class TestGoals:
    def test_progress_both_directions(self):
        assert gl.progress_pct(80, 77, 70, "down") == 30
        assert gl.progress_pct(80, 82, 70, "down") == 0
        assert gl.progress_pct(80, 65, 70, "down") == 100
        assert gl.progress_pct(3, 6, 10, "up") == 43
        assert gl.progress_pct(None, 11, 10, "up") == 100
        assert gl.progress_pct(3, None, 10, "up") is None

    def test_milestones(self):
        series = [(D0, 80.0), (D0 + dt.timedelta(days=10), 77.0),
                  (D0 + dt.timedelta(days=20), 74.5), (D0 + dt.timedelta(days=30), 72.0)]
        reached = gl.reached_on(series, 80.0, 70.0, "down")
        assert reached == {25: D0 + dt.timedelta(days=10), 50: D0 + dt.timedelta(days=20),
                           75: D0 + dt.timedelta(days=30), 100: None}

    def test_projection_from_a_linear_trend(self):
        today = D0 + dt.timedelta(days=30)
        series = [(D0 + dt.timedelta(days=i), 80 - i * 0.1) for i in range(0, 31, 3)]
        p = gl.project(series, 75.0, "down", today, target_date=today + dt.timedelta(days=60))
        assert p.date == today + dt.timedelta(days=20) and p.on_track is True
        assert p.method == "trend" and "Estimate" in p.note

    def test_projection_needs_data_and_movement(self):
        today = D0 + dt.timedelta(days=30)
        assert gl.project([(today, 80.0)], 75, "down", today).date is None
        flat = [(D0 + dt.timedelta(days=i), 80.0) for i in range(0, 31, 5)]
        p = gl.project(flat, 75, "down", today, target_date=today + dt.timedelta(days=9))
        assert p.date is None and p.on_track is False
        away = [(D0 + dt.timedelta(days=i), 80.0 + i / 10) for i in range(0, 31, 5)]
        assert gl.project(away, 75, "down", today).date is None

    def test_display(self):
        assert gl.display("race_time", 3150) == "52:30"
        assert gl.display("race_time", 6300) == "1:45:00"
        assert gl.display("weight", 68.42, "kg") == "68.4 kg"
        assert gl.direction(None, 3000, "race_time") == "down"
        assert gl.direction(5, 10, "distance") == "up"
