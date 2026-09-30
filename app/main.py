import hmac
import json
import time
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from bson import ObjectId
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, Response)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import config, db
from .services import logic as L

BASE = Path(__file__).parent


@asynccontextmanager
async def lifespan(app):
    db.init()
    yield


app = FastAPI(title="Winter Arc", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=config.SECRET_KEY,
                   max_age=60 * 60 * 24 * config.SESSION_DAYS,
                   same_site="lax", https_only=config.IS_RENDER)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


# ---------- auth ----------
class NeedLogin(Exception):
    pass


@app.exception_handler(NeedLogin)
async def need_login(request: Request, exc: NeedLogin):
    if request.headers.get("HX-Request"):
        return Response(status_code=200, headers={"HX-Redirect": "/login"})
    return RedirectResponse("/login", 303)


def auth(request: Request):
    if not request.session.get("ok"):
        raise NeedLogin()


_fails: dict = {}


def _ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def render(request: Request, name: str, **ctx):
    ctx.setdefault("nav", True)
    return templates.TemplateResponse(request, name, ctx)


def parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise HTTPException(400, "Invalid date")


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html", nav=False, error=None,
                  configured=bool(config.APP_PIN))


@app.post("/login")
def login(request: Request, pin: str = Form("")):
    ip = _ip(request)
    count, until = _fails.get(ip, (0, 0.0))
    if count >= 5 and time.time() < until:
        return render(request, "login.html", nav=False, configured=True,
                      error="Too many tries. Wait 15 minutes and try again.")
    if config.APP_PIN and hmac.compare_digest(pin.encode(), config.APP_PIN.encode()):
        _fails.pop(ip, None)
        request.session["ok"] = True
        return RedirectResponse("/", 303)
    count += 1
    _fails[ip] = (count, time.time() + 900 if count >= 5 else 0.0)
    return render(request, "login.html", nav=False, configured=bool(config.APP_PIN),
                  error="Wrong PIN." if config.APP_PIN else
                  "APP_PIN is not set on the server.")


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", 303)


# ---------- today ----------
def today_ctx(sel):
    arc = L.get_arc()
    tday = L.today()
    tasks = L.list_tasks()
    logmap = L.load_logmap()
    default = min(max(tday, arc["start"]), arc["end"])
    sel = min(max(sel or default, arc["start"]), arc["end"])
    state = "before" if tday < arc["start"] else ("after" if tday > arc["end"] else "active")
    info = L.day_info(sel, tasks, logmap)
    stats = L.build_stats(arc, tasks, logmap, tday)
    last_editable = min(tday, arc["end"])
    note = db.notes.find_one({"date": sel.isoformat()}) or {}
    return {
        "page": "today", "arc": arc, "sel": sel, "tday": tday, "state": state,
        "info": info, "editable": sel <= tday, "is_today": sel == tday,
        "day_no": (min(tday, arc["end"]) - arc["start"]).days + 1 if state != "before" else 0,
        "days_to_start": (arc["start"] - tday).days if state == "before" else 0,
        "sel_no": (sel - arc["start"]).days + 1,
        "prev": sel - timedelta(days=1) if sel > arc["start"] else None,
        "next": sel + timedelta(days=1) if sel < last_editable else None,
        "streak": stats["overall"], "tstreaks": stats["per_map"],
        "note": note.get("text", ""),
    }


@app.get("/", response_class=HTMLResponse)
def today_page(request: Request, d: str = "", _=Depends(auth)):
    sel = parse_date(d) if d else None
    return render(request, "today.html", **today_ctx(sel))


@app.post("/log", response_class=HTMLResponse)
def log_task(request: Request, date_: str = Form(..., alias="date"),
             task_id: str = Form(...), status: str = Form(...), _=Depends(auth)):
    d = parse_date(date_)
    arc = L.get_arc()
    if d < arc["start"] or d > min(L.today(), arc["end"]):
        raise HTTPException(400, "This day can't be edited yet")
    if status not in ("done", "min"):
        raise HTTPException(400, "Bad status")
    try:
        oid = ObjectId(task_id)
    except Exception:
        raise HTTPException(400, "Bad task")
    if not db.tasks.find_one({"_id": oid}):
        raise HTTPException(404, "Task not found")
    key = {"date": d.isoformat(), "task_id": task_id}
    cur = db.logs.find_one(key)
    if cur and cur["status"] == status:
        db.logs.delete_one(key)
    else:
        db.logs.update_one(key, {"$set": {"status": status, "ts": time.time()}}, upsert=True)
    return templates.TemplateResponse(request, "_today.html", today_ctx(d))


@app.post("/note", response_class=HTMLResponse)
def save_note(date_: str = Form(..., alias="date"), text: str = Form(""), _=Depends(auth)):
    d = parse_date(date_).isoformat()
    text = text.strip()[:2000]
    if text:
        db.notes.update_one({"date": d}, {"$set": {"text": text}}, upsert=True)
    else:
        db.notes.delete_one({"date": d})
    return HTMLResponse("Saved")


# ---------- stats ----------
@app.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request, _=Depends(auth)):
    arc = L.get_arc()
    s = L.build_stats(arc, L.list_tasks(), L.load_logmap(), L.today())
    return render(request, "stats.html", page="stats", arc=arc, s=s)


# ---------- tasks ----------
@app.get("/tasks", response_class=HTMLResponse)
def tasks_page(request: Request, _=Depends(auth)):
    ts = L.list_tasks()
    return render(request, "tasks.html", page="tasks",
                  active=[t for t in ts if not t.get("end_date")],
                  archived=[t for t in ts if t.get("end_date")])


@app.post("/tasks")
def add_task(name: str = Form(...), category: str = Form("General"),
             minimum: str = Form(""), order: int = Form(50), _=Depends(auth)):
    name = name.strip()[:80]
    if not name:
        raise HTTPException(400, "Name required")
    arc = L.get_arc()
    start = max(L.today(), arc["start"]).isoformat()
    db.tasks.insert_one({"name": name, "category": category.strip()[:30] or "General",
                         "minimum": minimum.strip()[:80], "order": order,
                         "start_date": start, "end_date": None})
    return RedirectResponse("/tasks", 303)


@app.post("/tasks/{task_id}/edit")
def edit_task(task_id: str, name: str = Form(...), category: str = Form("General"),
              minimum: str = Form(""), order: int = Form(50), _=Depends(auth)):
    db.tasks.update_one({"_id": ObjectId(task_id)}, {"$set": {
        "name": name.strip()[:80], "category": category.strip()[:30] or "General",
        "minimum": minimum.strip()[:80], "order": order}})
    return RedirectResponse("/tasks", 303)


@app.post("/tasks/{task_id}/archive")
def archive_task(task_id: str, _=Depends(auth)):
    db.tasks.update_one({"_id": ObjectId(task_id)},
                        {"$set": {"end_date": L.today().isoformat()}})
    return RedirectResponse("/tasks", 303)


# ---------- weekly review ----------
@app.get("/review", response_class=HTMLResponse)
def review_page(request: Request, _=Depends(auth)):
    arc = L.get_arc()
    s = L.build_stats(arc, L.list_tasks(), L.load_logmap(), L.today())
    saved = {r["week"]: r for r in db.reviews.find({})}
    shown = [w for w in s["weeks"] if w["no"] <= s["cur_week"]][::-1]
    return render(request, "review.html", page="review", arc=arc, weeks=shown,
                  saved=saved, cur_week=s["cur_week"])


@app.post("/review/{week}")
def save_review(week: int, wins: str = Form(""), misses: str = Form(""),
                adjust: str = Form(""), _=Depends(auth)):
    db.reviews.update_one({"week": week}, {"$set": {
        "wins": wins.strip()[:2000], "misses": misses.strip()[:2000],
        "adjust": adjust.strip()[:2000]}}, upsert=True)
    return RedirectResponse("/review", 303)


# ---------- settings ----------
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: int = 0, _=Depends(auth)):
    return render(request, "settings.html", page="settings", arc=L.get_arc(), saved=saved)


@app.post("/settings")
def save_settings(start_date: str = Form(...), shields: int = Form(4),
                  contract: str = Form(""), after: str = Form(""), _=Depends(auth)):
    new = parse_date(start_date)
    old = L.get_arc()["start"]
    if new != old:
        db.tasks.update_many({"start_date": old.isoformat()},
                             {"$set": {"start_date": new.isoformat()}})
    db.settings.update_one({"_id": "arc"}, {"$set": {
        "start_date": new.isoformat(), "shields": max(0, min(shields, 30)),
        "contract": contract.strip()[:3000], "after": after.strip()[:3000]}}, upsert=True)
    return RedirectResponse("/settings?saved=1", 303)


@app.get("/export.json")
def export(_=Depends(auth)):
    def clean(rows):
        out = []
        for r in rows:
            r = dict(r)
            if "_id" in r:
                r["_id"] = str(r["_id"])
            out.append(r)
        return out
    data = {"settings": clean(db.settings.find({})), "tasks": clean(db.tasks.find({})),
            "logs": clean(db.logs.find({})), "notes": clean(db.notes.find({})),
            "reviews": clean(db.reviews.find({}))}
    return Response(json.dumps(data, default=str, indent=1), media_type="application/json",
                    headers={"Content-Disposition": "attachment; filename=winter-arc-backup.json"})


# ---------- infra / PWA ----------
@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/manifest.webmanifest")
def manifest():
    return JSONResponse({
        "name": "Winter Arc", "short_name": "Winter Arc", "start_url": "/",
        "scope": "/", "display": "standalone", "background_color": "#09131f",
        "theme_color": "#09131f",
        "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png",
                   "purpose": "any maskable"}],
    }, media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    return FileResponse(BASE / "static" / "sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})
