from flask import Flask, render_template, request, jsonify
import logic

app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html", attendance=logic.get_attendance())


@app.route("/pricing")
def pricing():
    return render_template("pricing.html")


@app.route("/attendance", methods=["POST"])
def attendance():
    name = request.json["name"]
    return jsonify(logic.mark_attendance(name))


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
