import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

os.environ["USE_MOCK_DB"] = "1"
os.environ["APP_PIN"] = "1234"
_today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
os.environ["ARC_START_DATE"] = (_today - timedelta(days=3)).isoformat()

from fastapi.testclient import TestClient  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402


def test_flow():
    with TestClient(app) as c:
        assert c.get("/healthz").json() == {"ok": True}
        assert c.get("/", follow_redirects=False).status_code == 303
        assert c.post("/login", data={"pin": "bad"}).status_code == 200
        assert c.post("/login", data={"pin": "1234"}, follow_redirects=False).status_code == 303

        r = c.get("/")
        assert r.status_code == 200 and "Workout" in r.text and ">4<" in r.text

        tasks = list(db.tasks.find({}))
        assert len(tasks) == 6
        today = _today.isoformat()
        # log every task for today -> complete day, then toggle one off
        for t in tasks:
            r = c.post("/log", data={"date": today, "task_id": str(t["_id"]), "status": "done"})
            assert r.status_code == 200
        assert "Day complete" in r.text
        r = c.post("/log", data={"date": today, "task_id": str(tasks[0]["_id"]), "status": "done"})
        assert "Day complete" not in r.text
        # future day rejected
        future = (_today + timedelta(days=1)).isoformat()
        assert c.post("/log", data={"date": future, "task_id": str(tasks[0]["_id"]),
                                    "status": "done"}).status_code == 400

        assert c.post("/note", data={"date": today, "text": "good day"}).text == "Saved"
        for path in ["/stats", "/tasks", "/review", "/settings", "/export.json",
                     "/manifest.webmanifest", "/sw.js", f"/?d={today}"]:
            assert c.get(path).status_code == 200, path

        assert c.post("/tasks", data={"name": "Cold shower", "category": "Body",
                                      "minimum": "30 sec", "order": 9},
                      follow_redirects=False).status_code == 303
        assert db.tasks.count_documents({}) == 7
        assert c.post("/review/1", data={"wins": "x"}, follow_redirects=False).status_code == 303
        assert c.post("/settings", data={"start_date": os.environ["ARC_START_DATE"],
                                         "shields": 3}, follow_redirects=False).status_code == 303
