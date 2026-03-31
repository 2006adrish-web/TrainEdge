import json
from datetime import datetime, time, timezone, timedelta

FILE = "data.json"
IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_LATE_DEADLINE = "15:00"

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
            data = json.load(f)
    except Exception:
        data = {"attendance": [], "queue": []}

    data.setdefault("attendance", [])
    data.setdefault("queue", [])
    data.setdefault("settings", {})
    return data


def save(data):
    with open(FILE, "w") as f:
        json.dump(data, f, indent=2)


def parse_deadline(value):
    if not value:
        return time.fromisoformat(DEFAULT_LATE_DEADLINE)

    try:
        return time.fromisoformat(value)
    except ValueError:
        return time.fromisoformat(DEFAULT_LATE_DEADLINE)


def format_deadline(deadline_value):
    deadline = parse_deadline(deadline_value)
    return deadline.strftime("%I:%M %p").lstrip("0")


def get_settings():
    data = load()
    deadline = data["settings"].get("late_deadline", DEFAULT_LATE_DEADLINE)
    parsed_deadline = parse_deadline(deadline)
    normalized_deadline = parsed_deadline.strftime("%H:%M")
    return {
        "late_deadline": normalized_deadline,
        "late_deadline_label": format_deadline(normalized_deadline),
        "timezone": "IST",
    }


def update_late_deadline(deadline_value):
    parsed_deadline = parse_deadline(deadline_value)
    normalized_deadline = parsed_deadline.strftime("%H:%M")
    data = load()
    data["settings"]["late_deadline"] = normalized_deadline
    save(data)
    return get_settings()


def get_late_status(now, deadline_value):
    cutoff = parse_deadline(deadline_value)
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
    deadline_value = data["settings"].get("late_deadline", DEFAULT_LATE_DEADLINE)
    now = datetime.now(IST)
    late, cutoff_label = get_late_status(now, deadline_value)

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


def clear_attendance():
    data = load()
    cleared_count = len(data["attendance"])
    data["attendance"] = []
    save(data)
    return cleared_count


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
