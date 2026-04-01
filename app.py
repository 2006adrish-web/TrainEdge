import os
import sqlite3
from datetime import date

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
import logic

app = Flask(__name__)
app.secret_key = os.environ.get("TRAINEDGE_SECRET_KEY", "trainedge-dev-secret")

DATABASE_PATH = os.path.join(os.path.dirname(__file__), "database.db")


def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_current_club_id():
    club_id = session.get("club_id", 1)
    try:
        club_id = int(club_id)
        if club_id <= 0:
            club_id = 1
    except (TypeError, ValueError):
        club_id = 1
    print("Current club:", club_id)
    return club_id


def get_plan_limits(plan):
    if plan == "free":
        return {
            "max_players": 15,
            "replay": False,
        }
    elif plan == "pro":
        return {
            "max_players": 50,
            "replay": True,
        }
    else:
        return {
            "max_players": 9999,
            "replay": True,
        }


def get_club_plan(club_id):
    conn = get_db()
    try:
        club = conn.execute(
            "SELECT plan FROM clubs WHERE id = ?",
            (club_id,),
        ).fetchone()
    finally:
        conn.close()
    plan = (club["plan"] if club and club["plan"] else "free").lower()
    print("PLAN:", plan)
    return plan


def init_db():
    def table_exists(conn, table_name):
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def column_exists(conn, table_name, column_name):
        columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return any(column["name"] == column_name for column in columns)

    def ensure_club_column(conn, table_name):
        if not table_exists(conn, table_name):
            return
        if not column_exists(conn, table_name, "club_id"):
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN club_id INTEGER DEFAULT 1")
        conn.execute(f"UPDATE {table_name} SET club_id = 1 WHERE club_id IS NULL")

    conn = get_db()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clubs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                plan TEXT DEFAULT 'free'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                password_hash TEXT,
                club_id INTEGER,
                role TEXT,
                FOREIGN KEY (club_id) REFERENCES clubs (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                club_id INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (club_id) REFERENCES clubs (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                player_id INTEGER,
                date TEXT,
                status TEXT,
                club_id INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (player_id) REFERENCES players (id),
                FOREIGN KEY (club_id) REFERENCES clubs (id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                club_id INTEGER NOT NULL DEFAULT 1,
                start_time TEXT,
                end_time TEXT,
                FOREIGN KEY (club_id) REFERENCES clubs (id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_players_club_id ON players (club_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_attendance_club_id ON attendance (club_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_attendance_player_id ON attendance (player_id)")
        ensure_club_column(conn, "users")
        ensure_club_column(conn, "players")
        ensure_club_column(conn, "attendance")
        ensure_club_column(conn, "sessions")
        conn.commit()
    finally:
        conn.close()


def render_dashboard():
    club_id = get_current_club_id()
    conn = get_db()
    try:
        club = conn.execute(
            "SELECT id, name, plan FROM clubs WHERE id = ?",
            (club_id,),
        ).fetchone()
    finally:
        conn.close()

    return render_template(
        "index.html",
        attendance=logic.get_attendance(club_id),
        settings=logic.get_settings(club_id),
        club_plan=(club["plan"] if club else "free"),
    )


@app.context_processor
def inject_auth_state():
    return {"is_logged_in": "user_id" in session}


@app.route("/")
def home():
    return render_dashboard()


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/login")
    return render_dashboard()


@app.route("/pricing")
def pricing():
    return render_template("pricing.html")


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        club_name = request.form.get("club_name", "").strip()
        role = request.form.get("role", "").strip() or "coach"

        if not email or not password or not club_name:
            flash("Email, password, and club name are required.", "error")
            return render_template("register.html")

        conn = get_db()
        try:
            existing_user = conn.execute(
                "SELECT id FROM users WHERE email = ?",
                (email,),
            ).fetchone()
            if existing_user:
                flash("An account with that email already exists.", "error")
                return render_template("register.html")

            club_cursor = conn.execute(
                "INSERT INTO clubs (name) VALUES (?)",
                (club_name,),
            )
            club_id = club_cursor.lastrowid
            user_cursor = conn.execute(
                """
                INSERT INTO users (email, password_hash, club_id, role)
                VALUES (?, ?, ?, ?)
                """,
                (email, generate_password_hash(password), club_id, role),
            )
            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            flash("We could not create your account right now. Please try again.", "error")
            return render_template("register.html")
        finally:
            conn.close()

        session["user_id"] = user_cursor.lastrowid
        session["club_id"] = club_id
        flash("Account created successfully. You are now signed in.", "success")
        return redirect(url_for("dashboard"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please enter both email and password.", "error")
            return render_template("login.html")

        conn = get_db()
        try:
            user = conn.execute(
                """
                SELECT id, password_hash, club_id
                FROM users
                WHERE email = ?
                """,
                (email,),
            ).fetchone()
        except sqlite3.Error:
            flash("Login is temporarily unavailable. Please try again.", "error")
            return render_template("login.html")
        finally:
            conn.close()

        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid email or password.", "error")
            return render_template("login.html")

        session["user_id"] = user["id"]
        session["club_id"] = user["club_id"]
        flash("Welcome back.", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("club_id", None)
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


@app.route("/attendance", methods=["POST"])
def attendance():
    club_id = get_current_club_id()
    name = request.json["name"]
    return jsonify(logic.mark_attendance(name, club_id))


@app.route("/settings")
def get_settings():
    club_id = get_current_club_id()
    return jsonify(logic.get_settings(club_id))


@app.route("/settings/late-deadline", methods=["POST"])
def update_late_deadline():
    club_id = get_current_club_id()
    deadline = request.json["late_deadline"]
    return jsonify(logic.update_late_deadline(deadline, club_id))


@app.route("/attendance-list")
def attendance_list():
    club_id = get_current_club_id()
    return jsonify({"attendance": logic.get_attendance(club_id)})


@app.route("/attendance/clear", methods=["POST"])
def clear_attendance():
    club_id = get_current_club_id()
    cleared_count = logic.clear_attendance(club_id)
    return jsonify({"cleared": cleared_count})


@app.route("/queue", methods=["POST"])
def queue():
    club_id = get_current_club_id()
    name = request.json["name"]
    return jsonify(logic.add_queue(name, club_id))


@app.route("/next")
def next_p():
    club_id = get_current_club_id()
    return jsonify({"player": logic.next_player(club_id)})


@app.route("/players")
def players():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    club_id = get_current_club_id()
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, name FROM players WHERE club_id = ? ORDER BY id DESC",
            (club_id,),
        ).fetchall()
    finally:
        conn.close()
    return jsonify({"players": [dict(row) for row in rows]})


@app.route("/upgrade", methods=["POST"])
def upgrade():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    club_id = get_current_club_id()
    code = request.form.get("code", "").strip().lower()
    if not code and request.is_json:
        code = (request.json or {}).get("code", "").strip().lower()

    if code != "alumonisgreat":
        return jsonify({"ok": False, "message": "Invalid upgrade code."}), 400

    conn = get_db()
    try:
        conn.execute(
            "UPDATE clubs SET plan = 'pro' WHERE id = ?",
            (club_id,),
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "message": "Upgrade successful. Your club is now on PRO."})


@app.route("/add_player", methods=["POST"])
def add_player():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    club_id = get_current_club_id()
    plan = get_club_plan(club_id)
    limits = get_plan_limits(plan)
    name = request.form.get("name", "").strip()
    if not name and request.is_json:
        name = (request.json or {}).get("name", "").strip()

    if not name:
        return jsonify({"ok": False, "message": "Player name is required."}), 400

    conn = get_db()
    try:
        player_count = conn.execute(
            "SELECT COUNT(*) FROM players WHERE club_id = ?",
            (club_id,),
        ).fetchone()[0]
        if player_count >= limits["max_players"]:
            return jsonify(
                {
                    "ok": False,
                    "message": "Upgrade to Pro to add more players.",
                    "plan": plan,
                    "max_players": limits["max_players"],
                }
            ), 403

        cursor = conn.execute(
            "INSERT INTO players (name, club_id) VALUES (?, ?)",
            (name, club_id),
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "message": f"{name} added.", "player_id": cursor.lastrowid})


@app.route("/delete_player", methods=["POST"])
def delete_player():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    club_id = get_current_club_id()
    raw_player_id = request.form.get("id", "").strip()
    if not raw_player_id and request.is_json:
        raw_player_id = str((request.json or {}).get("id", "")).strip()

    try:
        player_id = int(raw_player_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Invalid player id."}), 400

    conn = get_db()
    try:
        result = conn.execute(
            "DELETE FROM players WHERE id = ? AND club_id = ?",
            (player_id, club_id),
        )
        conn.commit()
    finally:
        conn.close()

    if result.rowcount == 0:
        return jsonify({"ok": False, "message": "Player not found for this club."}), 404
    return jsonify({"ok": True, "message": "Player deleted."})


@app.route("/mark_attendance", methods=["POST"])
def mark_attendance():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    club_id = get_current_club_id()
    raw_player_id = request.form.get("player_id", "").strip()
    status = request.form.get("status", "").strip().lower()

    if request.is_json:
        payload = request.json or {}
        if not raw_player_id:
            raw_player_id = str(payload.get("player_id", "")).strip()
        if not status:
            status = str(payload.get("status", "")).strip().lower()

    try:
        player_id = int(raw_player_id)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Invalid player id."}), 400

    if status not in {"present", "late"}:
        return jsonify({"ok": False, "message": "Status must be 'present' or 'late'."}), 400

    conn = get_db()
    try:
        player = conn.execute(
            "SELECT id FROM players WHERE id = ? AND club_id = ?",
            (player_id, club_id),
        ).fetchone()
        if not player:
            return jsonify({"ok": False, "message": "Player not found for this club."}), 404

        conn.execute(
            """
            INSERT INTO attendance (player_id, date, status, club_id)
            VALUES (?, ?, ?, ?)
            """,
            (player_id, date.today().isoformat(), status, club_id),
        )
        conn.commit()
    finally:
        conn.close()

    return jsonify({"ok": True, "message": f"Attendance marked: {status}."})


@app.route("/mark_present_bulk", methods=["POST"])
def mark_present_bulk():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    club_id = get_current_club_id()
    plan = get_club_plan(club_id)
    limits = get_plan_limits(plan)
    today = date.today().isoformat()

    names_input = request.form.get("players", "")
    if not names_input and request.is_json:
        names_input = str((request.json or {}).get("players", ""))

    names = [name.strip() for name in names_input.split(",") if name.strip()]
    if not names:
        return jsonify({"ok": False, "message": "Enter at least one player name."}), 400

    # Prevent duplicate names in a single bulk request (case-insensitive)
    unique_names = []
    seen = set()
    for raw_name in names:
        key = raw_name.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_names.append(raw_name)

    conn = get_db()
    try:
        existing_player_count = conn.execute(
            "SELECT COUNT(*) FROM players WHERE club_id = ?",
            (club_id,),
        ).fetchone()[0]

        created_count = 0
        marked_count = 0
        skipped_count = 0
        blocked_by_limit = 0

        for name in unique_names:
            player = conn.execute(
                "SELECT id FROM players WHERE lower(name) = lower(?) AND club_id = ?",
                (name, club_id),
            ).fetchone()

            if player:
                player_id = player["id"]
            else:
                if existing_player_count >= limits["max_players"]:
                    blocked_by_limit += 1
                    continue
                cursor = conn.execute(
                    "INSERT INTO players (name, club_id) VALUES (?, ?)",
                    (name, club_id),
                )
                player_id = cursor.lastrowid
                existing_player_count += 1
                created_count += 1

            already_marked = conn.execute(
                """
                SELECT id
                FROM attendance
                WHERE player_id = ? AND date = ? AND club_id = ?
                """,
                (player_id, today, club_id),
            ).fetchone()
            if already_marked:
                skipped_count += 1
                continue

            conn.execute(
                """
                INSERT INTO attendance (player_id, date, status, club_id)
                VALUES (?, ?, 'present', ?)
                """,
                (player_id, today, club_id),
            )
            marked_count += 1

        conn.commit()
    finally:
        conn.close()

    message = f"Attendance marked for {marked_count} players"
    if skipped_count:
        message += f" ({skipped_count} already marked today)"
    if blocked_by_limit:
        message += f". {blocked_by_limit} not added due to plan limit"

    return jsonify(
        {
            "ok": True,
            "message": message,
            "marked": marked_count,
            "created": created_count,
            "skipped": skipped_count,
            "blocked": blocked_by_limit,
        }
    )


@app.route("/replay/access")
def replay_access():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    club_id = get_current_club_id()
    plan = get_club_plan(club_id)
    limits = get_plan_limits(plan)

    if not limits["replay"]:
        return jsonify({"ok": False, "message": "Replay available only in Pro plan."}), 403
    return jsonify({"ok": True, "plan": plan})


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
