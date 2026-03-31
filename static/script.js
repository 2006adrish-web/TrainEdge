const feedback = document.getElementById("feedback");
const currentPlayer = document.getElementById("current");
const timerDisplay = document.getElementById("timer");
const attendanceList = document.getElementById("attendance-list");
const lateDeadlineInput = document.getElementById("late-deadline");
const lateDeadlineStatus = document.getElementById("late-deadline-status");

function showFeedback(message, type = "success") {
    if (!feedback) {
        return;
    }

    feedback.textContent = message;
    feedback.className = `feedback is-${type}`;
}

function renderAttendance(records) {
    if (!attendanceList) {
        return;
    }

    if (!records.length) {
        attendanceList.innerHTML = `
            <tr>
                <td colspan="4" class="empty-state">No attendance has been recorded yet.</td>
            </tr>
        `;
        return;
    }

    attendanceList.innerHTML = records.map((student) => `
        <tr>
            <td>${student.name}</td>
            <td>${student.day}</td>
            <td>${student.time}</td>
            <td>
                <span class="pill ${student.late ? "pill-late" : "pill-on-time"}">
                    ${student.status}
                </span>
            </td>
        </tr>
    `).join("");
}

async function loadAttendance() {
    if (!attendanceList) {
        return;
    }

    const res = await fetch("/attendance-list");
    const data = await res.json();
    renderAttendance(data.attendance || []);
}

async function saveLateDeadline() {
    if (!lateDeadlineInput) {
        return;
    }

    const late_deadline = lateDeadlineInput.value;

    if (!late_deadline) {
        showFeedback("Choose the IST time after which attendance should count as late.", "warning");
        lateDeadlineInput.focus();
        return;
    }

    const res = await fetch("/settings/late-deadline", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ late_deadline })
    });
    const data = await res.json();

    updateLateDeadlineStatus(data);
    showFeedback(`Late deadline saved. Players checking in after ${data.late_deadline_label} IST will be marked late.`, "success");
}

function updateLateDeadlineStatus(settings) {
    if (lateDeadlineInput && settings.late_deadline) {
        lateDeadlineInput.value = settings.late_deadline;
    }

    if (lateDeadlineStatus && settings.late_deadline_label) {
        lateDeadlineStatus.innerText = `After ${settings.late_deadline_label} IST`;
    }
}

async function clearAttendance() {
    if (!attendanceList) {
        return;
    }

    const confirmed = window.confirm("Clear all marked attendance for the next day?");
    if (!confirmed) {
        return;
    }

    const res = await fetch("/attendance/clear", {
        method: "POST"
    });
    const data = await res.json();

    await loadAttendance();
    showFeedback(
        data.cleared ? `${data.cleared} attendance record${data.cleared === 1 ? "" : "s"} cleared.` : "Attendance list is already empty.",
        data.cleared ? "warning" : "success"
    );
}

async function mark() {
    const nameInput = document.getElementById("name");
    const name = nameInput.value.trim();

    if (!name) {
        showFeedback("Enter a player name before marking attendance.", "warning");
        nameInput.focus();
        return;
    }

    const res = await fetch("/attendance", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name })
    });

    const data = await res.json();
    const lateText = data.late
        ? ` Marked late for ${data.day} because the cutoff is ${data.cutoff} IST.`
        : ` On time for ${data.day}.`;

    showFeedback(`${data.name} checked in at ${data.time}.${lateText}`, data.late ? "warning" : "success");
    nameInput.value = "";
    await loadAttendance();
}

async function add() {
    const queueInput = document.getElementById("qname");
    const name = queueInput.value.trim();

    if (!name) {
        showFeedback("Add a player name before sending them to the queue.", "warning");
        queueInput.focus();
        return;
    }

    await fetch("/queue", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name })
    });

    showFeedback(`${name} added to the batting queue.`, "success");
    queueInput.value = "";
}

async function next() {
    const res = await fetch("/next");
    const data = await res.json();

    if (currentPlayer) {
        currentPlayer.innerText = data.player ? `Now batting: ${data.player}` : "Queue empty";
    }

    showFeedback(
        data.player ? `${data.player} is now up.` : "The queue is empty right now.",
        data.player ? "success" : "warning"
    );
}

let interval;

function startTimer() {
    const timeInput = document.getElementById("time");
    const mins = Number(timeInput.value);

    if (!timeInput || !timerDisplay) {
        return;
    }

    if (!mins || mins <= 0) {
        showFeedback("Set a timer duration greater than zero.", "warning");
        timeInput.focus();
        return;
    }

    let seconds = mins * 60;
    clearInterval(interval);

    showFeedback(`Timer started for ${mins} minute${mins > 1 ? "s" : ""}.`, "success");
    updateTimerDisplay(seconds);

    interval = setInterval(() => {
        seconds -= 1;

        if (seconds < 0) {
            clearInterval(interval);
            timerDisplay.innerText = "00:00";
            showFeedback("Time is up. Move to the next drill.", "warning");
            return;
        }

        updateTimerDisplay(seconds);
    }, 1000);
}

function updateTimerDisplay(totalSeconds) {
    if (!timerDisplay) {
        return;
    }

    const m = Math.floor(totalSeconds / 60);
    const s = totalSeconds % 60;
    timerDisplay.innerText = `${m}:${s < 10 ? "0" : ""}${s}`;
}

if (attendanceList) {
    loadAttendance();
}
