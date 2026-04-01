import os
import sqlite3

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


def init_db():
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
        conn.commit()
    finally:
        conn.close()


def render_dashboard():
    return render_template(
        "index.html",
        attendance=logic.get_attendance(),
        settings=logic.get_settings(),
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
    name = request.json["name"]
    return jsonify(logic.mark_attendance(name))


@app.route("/settings")
def get_settings():
    return jsonify(logic.get_settings())


@app.route("/settings/late-deadline", methods=["POST"])
def update_late_deadline():
    deadline = request.json["late_deadline"]
    return jsonify(logic.update_late_deadline(deadline))


@app.route("/attendance-list")
def attendance_list():
    return jsonify({"attendance": logic.get_attendance()})


@app.route("/attendance/clear", methods=["POST"])
def clear_attendance():
    cleared_count = logic.clear_attendance()
    return jsonify({"cleared": cleared_count})


@app.route("/queue", methods=["POST"])
def queue():
    name = request.json["name"]
    return jsonify(logic.add_queue(name))


@app.route("/next")
def next_p():
    return jsonify({"player": logic.next_player()})


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
