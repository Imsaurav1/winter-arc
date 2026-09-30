from collections import defaultdict
from datetime import date, datetime, timedelta

from .. import db
from ..config import DEFAULT_START, TZ

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def today() -> date:
    return datetime.now(TZ).date()


def pct(a, b) -> int:
    return round(100 * a / b) if b else 0


def get_arc() -> dict:
    doc = db.settings.find_one({"_id": "arc"}) or {}
    start = date.fromisoformat(doc.get("start_date", DEFAULT_START))
    days = int(doc.get("days", 90))
    return {
        "start": start, "days": days, "end": start + timedelta(days=days - 1),
        "shields": int(doc.get("shields", 4)),
        "contract": doc.get("contract", ""), "after": doc.get("after", ""),
    }


def list_tasks() -> list:
    ts = list(db.tasks.find({}))
    for t in ts:
        t["id"] = str(t["_id"])
        t["end_date"] = t.get("end_date")
    ts.sort(key=lambda t: (t.get("order", 0), t["id"]))
    return ts


def active_on(t: dict, d: date) -> bool:
    s = d.isoformat()
    return t["start_date"] <= s and (not t.get("end_date") or s < t["end_date"])


def load_logmap() -> dict:
    m = defaultdict(dict)
    for l in db.logs.find({}, {"_id": 0}):
        m[l["date"]][l["task_id"]] = l["status"]
    return m


def day_info(d: date, tasks: list, logmap: dict) -> dict:
    act = [t for t in tasks if active_on(t, d)]
    st = logmap.get(d.isoformat(), {})
    done = sum(1 for t in act if st.get(t["id"]) == "done")
    mins = sum(1 for t in act if st.get(t["id"]) == "min")
    total = len(act)
    return {"date": d, "active": act, "status": st, "done": done, "mins": mins,
            "total": total, "logged": done + mins,
            "complete": total > 0 and done + mins == total}


def overall_streak(arc: dict, tasks: list, logmap: dict, tday: date) -> dict:
    """Streak of fully completed days. A missed day spends a shield (if any
    are left and a streak is running) instead of resetting the streak."""
    cur = longest = used = 0
    last = min(tday, arc["end"])
    d = arc["start"]
    while d <= last:
        info = day_info(d, tasks, logmap)
        if info["total"] == 0:
            pass
        elif info["complete"]:
            cur += 1
            longest = max(longest, cur)
        elif d == tday:
            pass  # today still open
        elif cur > 0 and used < arc["shields"]:
            used += 1
        else:
            cur = 0
        d += timedelta(days=1)
    return {"current": cur, "longest": longest, "shields_used": used,
            "shields_left": max(arc["shields"] - used, 0)}


def build_stats(arc: dict, tasks: list, logmap: dict, tday: date) -> dict:
    per = {t["id"]: {"t": t, "done": 0, "mins": 0, "days": 0, "cur": 0, "longest": 0}
           for t in tasks}
    wd = [[0, 0] for _ in range(7)]
    cat = defaultdict(lambda: [0, 0])
    nweeks = -(-arc["days"] // 7)
    wk = [[0, 0] for _ in range(nweeks)]
    perfect = 0
    heat = []
    for i in range(arc["days"]):
        d = arc["start"] + timedelta(days=i)
        info = day_info(d, tasks, logmap)
        future = d > tday
        if not future:
            for t in info["active"]:
                s = info["status"].get(t["id"])
                if not s and d == tday:
                    continue
                p = per[t["id"]]
                p["days"] += 1
                ok = 1 if s else 0
                if s:
                    p["cur"] += 1
                    p["longest"] = max(p["longest"], p["cur"])
                    p["done" if s == "done" else "mins"] += 1
                else:
                    p["cur"] = 0
                c = cat[t.get("category") or "General"]
                c[0] += ok; c[1] += 1
                wd[d.weekday()][0] += ok; wd[d.weekday()][1] += 1
                wk[i // 7][0] += ok; wk[i // 7][1] += 1
        if info["complete"]:
            perfect += 1
        if future or info["total"] == 0 or info["logged"] == 0:
            level = 0
        elif not info["complete"]:
            level = 1 if info["logged"] / info["total"] < 0.5 else 2
        else:
            level = 3 if info["mins"] else 4
        heat.append({"date": d, "iso": d.isoformat(), "dayno": i + 1, "level": level,
                     "future": future, "today": d == tday,
                     "title": f"Day {i + 1}, {d:%d %b}: {info['logged']}/{info['total']}"})

    per_task = [dict(p, pct=pct(p["done"] + p["mins"], p["days"]))
                for p in per.values()
                if p["days"] > 0 or not p["t"].get("end_date")]
    started = tday >= arc["start"]
    cur_week = (min(tday, arc["end"]) - arc["start"]).days // 7 + 1 if started else 0
    weeks = []
    for i in range(nweeks):
        s = arc["start"] + timedelta(days=7 * i)
        e = min(s + timedelta(days=6), arc["end"])
        weeks.append({"no": i + 1, "start": s, "end": e,
                      "pct": pct(*wk[i]) if wk[i][1] else None})
    return {
        "per_task": per_task,
        "per_map": per,
        "overall": overall_streak(arc, tasks, logmap, tday),
        "overall_pct": pct(sum(w[0] for w in wk), sum(w[1] for w in wk)),
        "perfect": perfect,
        "weekday": [{"name": WEEKDAYS[i], "pct": pct(*wd[i]), "has": wd[i][1] > 0}
                    for i in range(7)],
        "categories": sorted(({"name": k, "pct": pct(*v)} for k, v in cat.items()),
                             key=lambda x: -x["pct"]),
        "weeks": weeks, "cur_week": cur_week,
        "heat": heat, "offset": arc["start"].weekday(),
    }
