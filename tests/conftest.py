import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Must run before any `app` import so config picks these up.
os.environ["USE_MOCK_DB"] = "1"
os.environ["APP_PIN"] = "1234"
_today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
os.environ["ARC_START_DATE"] = (_today - timedelta(days=3)).isoformat()
