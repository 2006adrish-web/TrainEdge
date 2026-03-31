const feedback = document.getElementById("feedback");
const currentPlayer = document.getElementById("current");
const timerDisplay = document.getElementById("timer");
const attendanceList = document.getElementById("attendance-list");
const lateDeadlineInput = document.getElementById("late-deadline");
const lateDeadlineStatus = document.getElementById("late-deadline-status");
const replayVideo = document.getElementById("replay-video");
const replayStatus = document.getElementById("replay-status");

let cameraStream = null;
let mediaRecorder = null;
let recordedChunks = [];
let lastClipBlob = null;
let lastClipUrl = null;

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

function updateReplayStatus(message) {
    if (!replayStatus) {
        return;
    }

    replayStatus.innerText = message;
}

function setLivePreview() {
    if (!replayVideo || !cameraStream) {
        return;
    }

    replayVideo.pause();
    replayVideo.controls = false;
    replayVideo.muted = true;
    replayVideo.src = "";
    replayVideo.srcObject = cameraStream;
}

function resetLastClipUrl() {
    if (!lastClipUrl) {
        return;
    }

    URL.revokeObjectURL(lastClipUrl);
    lastClipUrl = null;
}

function getSupportedMimeType() {
    if (!window.MediaRecorder) {
        return "";
    }

    const mimeTypes = [
        "video/webm;codecs=vp9",
        "video/webm;codecs=vp8",
        "video/webm",
        "video/mp4"
    ];

    for (const mimeType of mimeTypes) {
        if (MediaRecorder.isTypeSupported(mimeType)) {
            return mimeType;
        }
    }

    return "";
}

async function startCamera() {
    if (!replayVideo) {
        return;
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        showFeedback("This browser does not support camera access.", "error");
        updateReplayStatus("Camera unsupported");
        return;
    }

    try {
        if (cameraStream) {
            setLivePreview();
            await replayVideo.play();
            updateReplayStatus("Camera is live");
            showFeedback("Camera is already running.", "success");
            return;
        }

        cameraStream = await navigator.mediaDevices.getUserMedia({
            video: { facingMode: "environment" },
            audio: false
        });

        setLivePreview();
        await replayVideo.play();
        updateReplayStatus("Camera is live");
        showFeedback("Camera started. You can record the next ball now.", "success");
    } catch (error) {
        console.error(error);
        updateReplayStatus("Camera permission denied");
        showFeedback("Camera access was denied or unavailable on this device.", "error");
    }
}

async function startRecording() {
    if (!window.MediaRecorder) {
        showFeedback("This browser does not support video recording.", "error");
        updateReplayStatus("Recording unsupported");
        return;
    }

    if (!cameraStream) {
        await startCamera();
    }

    if (!cameraStream) {
        return;
    }

    if (mediaRecorder && mediaRecorder.state === "recording") {
        showFeedback("Recording is already in progress.", "warning");
        return;
    }

    const mimeType = getSupportedMimeType();
    const recorderOptions = mimeType ? { mimeType } : undefined;

    recordedChunks = [];
    mediaRecorder = new MediaRecorder(cameraStream, recorderOptions);

    mediaRecorder.addEventListener("dataavailable", (event) => {
        if (event.data && event.data.size > 0) {
            recordedChunks.push(event.data);
        }
    });

    mediaRecorder.addEventListener("stop", () => {
        if (!recordedChunks.length) {
            updateReplayStatus("No clip recorded");
            showFeedback("Recording stopped, but no clip was captured.", "warning");
            return;
        }

        const clipType = mimeType || recordedChunks[0].type || "video/webm";
        lastClipBlob = new Blob(recordedChunks, { type: clipType });
        updateReplayStatus("Last clip is ready");
        showFeedback("Recording saved. Tap replay to review the last ball.", "success");
    });

    mediaRecorder.start();
    updateReplayStatus("Recording in progress");
    showFeedback("Recording started.", "success");
}

function stopRecording() {
    if (!mediaRecorder || mediaRecorder.state !== "recording") {
        showFeedback("No active recording to stop.", "warning");
        return;
    }

    mediaRecorder.stop();
    updateReplayStatus("Saving clip");
}

async function replayLastClip() {
    if (!replayVideo) {
        return;
    }

    if (!lastClipBlob) {
        showFeedback("Record a clip first to replay the last ball.", "warning");
        updateReplayStatus("No clip available");
        return;
    }

    resetLastClipUrl();
    lastClipUrl = URL.createObjectURL(lastClipBlob);

    replayVideo.pause();
    replayVideo.srcObject = null;
    replayVideo.src = lastClipUrl;
    replayVideo.controls = true;
    replayVideo.muted = false;
    replayVideo.currentTime = 0;

    try {
        await replayVideo.play();
        updateReplayStatus("Playing last clip");
        showFeedback("Replaying the last recorded clip.", "success");
    } catch (error) {
        console.error(error);
        showFeedback("Replay could not start automatically. Use the video controls to play it.", "warning");
    }
}

if (replayVideo) {
    replayVideo.addEventListener("ended", () => {
        if (!cameraStream || mediaRecorder?.state === "recording") {
            return;
        }

        setLivePreview();
        replayVideo.play().catch(() => {});
        updateReplayStatus("Camera is live");
    });
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
