import os
from zoneinfo import ZoneInfo

MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "winter_arc")
APP_PIN = os.environ.get("APP_PIN", "")
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
TZ = ZoneInfo(os.environ.get("APP_TZ", "Asia/Kolkata"))
DEFAULT_START = os.environ.get("ARC_START_DATE", "2026-10-01")
IS_RENDER = bool(os.environ.get("RENDER"))
SESSION_DAYS = 120
