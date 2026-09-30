import os

from pymongo import MongoClient

from .config import DB_NAME, DEFAULT_START, MONGO_URI

if os.environ.get("USE_MOCK_DB") == "1":
    import mongomock

    client = mongomock.MongoClient()
else:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)

db = client[DB_NAME]
tasks = db.tasks
logs = db.logs
notes = db.notes
reviews = db.reviews
settings = db.settings

DEFAULT_TASKS = [
    ("Workout", "Body", "10 minute walk"),
    ("Read 10 pages", "Mind", "1 page"),
    ("Wake before 6:30", "Discipline", "Wake before 7:30"),
    ("Deep work, 2 hours", "Growth", "30 minutes"),
    ("Clean eating, no junk", "Body", "One clean meal"),
    ("In bed by 11 pm", "Recovery", "In bed by midnight"),
]


def init():
    logs.create_index([("date", 1), ("task_id", 1)], unique=True)
    notes.create_index("date", unique=True)
    reviews.create_index("week", unique=True)
    if settings.count_documents({"_id": "arc"}) == 0:
        settings.insert_one(
            {"_id": "arc", "start_date": DEFAULT_START, "days": 90, "shields": 4,
             "contract": "", "after": ""}
        )
    if tasks.count_documents({}) == 0:
        start = settings.find_one({"_id": "arc"})["start_date"]
        for i, (name, cat, mini) in enumerate(DEFAULT_TASKS):
            tasks.insert_one({"name": name, "category": cat, "minimum": mini,
                              "order": i, "start_date": start, "end_date": None})
