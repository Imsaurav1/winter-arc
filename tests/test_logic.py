import os
os.environ["USE_MOCK_DB"] = "1"
from datetime import date, timedelta

from app.services import logic as L


def mk(tasks=2):
    return [{"id": str(i), "name": f"t{i}", "category": "c", "start_date": "2026-10-01",
             "end_date": None} for i in range(tasks)]


def test_shield_keeps_streak():
    arc = {"start": date(2026, 10, 1), "days": 90, "end": date(2026, 12, 29), "shields": 1}
    ts = mk(1)
    lm = {"2026-10-01": {"0": "done"}, "2026-10-02": {"0": "min"},
          "2026-10-04": {"0": "done"}}  # Oct 3 missed -> shield
    r = L.overall_streak(arc, ts, lm, date(2026, 10, 4))
    assert r["current"] == 3 and r["shields_left"] == 0


def test_no_shield_resets():
    arc = {"start": date(2026, 10, 1), "days": 90, "end": date(2026, 12, 29), "shields": 0}
    ts = mk(1)
    lm = {"2026-10-01": {"0": "done"}, "2026-10-03": {"0": "done"}}
    r = L.overall_streak(arc, ts, lm, date(2026, 10, 3))
    assert r["current"] == 1 and r["longest"] == 1


def test_today_open_does_not_break():
    arc = {"start": date(2026, 10, 1), "days": 90, "end": date(2026, 12, 29), "shields": 0}
    ts = mk(1)
    lm = {"2026-10-01": {"0": "done"}, "2026-10-02": {"0": "done"}}
    r = L.overall_streak(arc, ts, lm, date(2026, 10, 3))
    assert r["current"] == 2


def test_stats_shape():
    arc = {"start": date(2026, 10, 1), "days": 90, "end": date(2026, 12, 29), "shields": 4}
    s = L.build_stats(arc, mk(2), {"2026-10-01": {"0": "done", "1": "min"}}, date(2026, 10, 2))
    assert len(s["heat"]) == 90 and len(s["weeks"]) == 13
    assert s["heat"][0]["level"] == 3 and s["perfect"] == 1
