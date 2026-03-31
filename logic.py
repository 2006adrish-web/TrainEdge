import json
from datetime import datetime, time

FILE = "data.json"

LATE_RULES = {
    0: time(15, 0),  # Monday
    2: time(15, 0),  # Wednesday
    5: time(8, 0),   # Saturday
    6: time(8, 0),   # Sunday
}

DAY_NAMES = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}


def load():
    try:
        with open(FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {"attendance": [], "queue": []}


def save(data):
    with open(FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_late_status(now):
    weekday = now.weekday()
    cutoff = LATE_RULES.get(weekday)

    if not cutoff:
        return False, None

    return now.time() > cutoff, cutoff.strftime("%I:%M %p").lstrip("0")


def normalize_record(record):
    late = bool(record.get("late", False))
    return {
        "name": record.get("name", "Unknown"),
        "day": record.get("day", "Recorded"),
        "time": record.get("time", "--:--"),
        "late": late,
        "status": record.get("status", "Late" if late else "On time"),
        "cutoff": record.get("cutoff"),
    }


def mark_attendance(name):
    data = load()
    now = datetime.now()
    late, cutoff_label = get_late_status(now)

    record = {
        "name": name,
        "day": DAY_NAMES[now.weekday()],
        "time": now.strftime("%H:%M"),
        "late": late,
        "status": "Late" if late else "On time",
        "cutoff": cutoff_label,
    }

    data["attendance"].append(record)
    save(data)
    return record


def get_attendance():
    data = load()
    return [normalize_record(record) for record in reversed(data["attendance"])]


def add_queue(name):
    data = load()
    data["queue"].append(name)
    save(data)
    return data["queue"]


def next_player():
    data = load()
    if data["queue"]:
        player = data["queue"].pop(0)
        save(data)
        return player
    return None
