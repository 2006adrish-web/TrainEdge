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


def default_club_data():
    return {"attendance": [], "queue": [], "settings": {}}


def default_data():
    return {"clubs": {"1": default_club_data()}}


def normalize_data(data):
    if not isinstance(data, dict):
        return default_data(), True

    clubs = data.get("clubs")
    if isinstance(clubs, dict):
        normalized_clubs = {}
        for club_key, club_data in clubs.items():
            if not isinstance(club_data, dict):
                club_data = {}
            normalized_clubs[str(club_key)] = {
                "attendance": club_data.get("attendance", []),
                "queue": club_data.get("queue", []),
                "settings": club_data.get("settings", {}),
            }
        if not normalized_clubs:
            normalized_clubs["1"] = default_club_data()
        return {"clubs": normalized_clubs}, False

    # Legacy shape migration: global attendance/queue/settings -> club_id 1
    migrated = {
        "clubs": {
            "1": {
                "attendance": data.get("attendance", []),
                "queue": data.get("queue", []),
                "settings": data.get("settings", {}),
            }
        }
    }
    return migrated, True


def club_key(club_id):
    try:
        normalized = int(club_id)
        if normalized <= 0:
            return "1"
        return str(normalized)
    except (TypeError, ValueError):
        return "1"


def get_club_data(data, club_id):
    key = club_key(club_id)
    clubs = data.setdefault("clubs", {})
    if key not in clubs or not isinstance(clubs.get(key), dict):
        clubs[key] = default_club_data()
    club_data = clubs[key]
    club_data.setdefault("attendance", [])
    club_data.setdefault("queue", [])
    club_data.setdefault("settings", {})
    return club_data


def load():
    try:
        with open(FILE, "r") as f:
            data = json.load(f)
    except Exception:
        data = default_data()

    normalized, migrated = normalize_data(data)
    if migrated:
        save(normalized)
    return normalized


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


def get_settings(club_id=1):
    data = load()
    club_data = get_club_data(data, club_id)
    deadline = club_data["settings"].get("late_deadline", DEFAULT_LATE_DEADLINE)
    parsed_deadline = parse_deadline(deadline)
    normalized_deadline = parsed_deadline.strftime("%H:%M")
    return {
        "late_deadline": normalized_deadline,
        "late_deadline_label": format_deadline(normalized_deadline),
        "timezone": "IST",
    }


def update_late_deadline(deadline_value, club_id=1):
    parsed_deadline = parse_deadline(deadline_value)
    normalized_deadline = parsed_deadline.strftime("%H:%M")
    data = load()
    club_data = get_club_data(data, club_id)
    club_data["settings"]["late_deadline"] = normalized_deadline
    save(data)
    return get_settings(club_id)


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


def mark_attendance(name, club_id=1):
    data = load()
    club_data = get_club_data(data, club_id)
    deadline_value = club_data["settings"].get("late_deadline", DEFAULT_LATE_DEADLINE)
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

    club_data["attendance"].append(record)
    save(data)
    return record


def get_attendance(club_id=1):
    data = load()
    club_data = get_club_data(data, club_id)
    return [normalize_record(record) for record in reversed(club_data["attendance"])]


def clear_attendance(club_id=1):
    data = load()
    club_data = get_club_data(data, club_id)
    cleared_count = len(club_data["attendance"])
    club_data["attendance"] = []
    save(data)
    return cleared_count


def add_queue(name, club_id=1):
    data = load()
    club_data = get_club_data(data, club_id)
    club_data["queue"].append(name)
    save(data)
    return club_data["queue"]


def next_player(club_id=1):
    data = load()
    club_data = get_club_data(data, club_id)
    if club_data["queue"]:
        player = club_data["queue"].pop(0)
        save(data)
        return player
    return None
