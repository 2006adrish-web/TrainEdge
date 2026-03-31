from flask import Flask, render_template, request, jsonify
import logic

app = Flask(__name__)


@app.route("/")
def home():
    return render_template(
        "index.html",
        attendance=logic.get_attendance(),
        settings=logic.get_settings(),
    )


@app.route("/pricing")
def pricing():
    return render_template("pricing.html")


@app.route("/about")
def about():
    return render_template("about.html")


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
