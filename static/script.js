const feedback = document.getElementById("feedback");
const currentPlayer = document.getElementById("current");
const timerDisplay = document.getElementById("timer");
const attendanceList = document.getElementById("attendance-list");
const lateDeadlineInput = document.getElementById("late-deadline");
const lateDeadlineStatus = document.getElementById("late-deadline-status");
const replayVideo = document.getElementById("replay-video");
const replayStatus = document.getElementById("replay-status");
const trackingOverlay = document.getElementById("tracking-overlay");
const upgradeCodeInput = document.getElementById("upgrade-code");
const playerNameInput = document.getElementById("player-name");
const playerList = document.getElementById("player-list");
const bulkPresentNamesInput = document.getElementById("bulk-present-names");

let cameraStream = null;
let mediaRecorder = null;
let recordedChunks = [];
let lastClipBlob = null;
let lastClipUrl = null;
let trackingEnabled = false;
let trackingFrameId = null;
let hiddenTrackingCanvas = null;
let hiddenTrackingContext = null;
let trackingOverlayContext = null;
let lastTrackingTimestamp = 0;
let trailPoints = [];

const TRACKING_COLOR = {
    redMin: 150,
    greenMax: 120,
    blueMax: 120
};
const TRACKING_FRAME_INTERVAL = 80;
const MAX_TRAIL_POINTS = 25;
let replayAllowedCache = null;

function showFeedback(message, type = "success") {
    if (!feedback) {
        return;
    }

    feedback.textContent = message;
    feedback.className = `feedback is-${type}`;
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
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

function ensureTrackingContexts() {
    if (!trackingOverlay || !replayVideo) {
        return false;
    }

    if (!trackingOverlayContext) {
        trackingOverlayContext = trackingOverlay.getContext("2d");
    }

    if (!hiddenTrackingCanvas) {
        hiddenTrackingCanvas = document.createElement("canvas");
        hiddenTrackingContext = hiddenTrackingCanvas.getContext("2d", { willReadFrequently: true });
    }

    if (!trackingOverlayContext || !hiddenTrackingContext) {
        return false;
    }

    return true;
}

function syncTrackingCanvasSize() {
    if (!ensureTrackingContexts()) {
        return false;
    }

    const width = replayVideo.videoWidth || replayVideo.clientWidth;
    const height = replayVideo.videoHeight || replayVideo.clientHeight;

    if (!width || !height) {
        return false;
    }

    if (trackingOverlay.width !== width || trackingOverlay.height !== height) {
        trackingOverlay.width = width;
        trackingOverlay.height = height;
    }

    if (hiddenTrackingCanvas.width !== width || hiddenTrackingCanvas.height !== height) {
        hiddenTrackingCanvas.width = width;
        hiddenTrackingCanvas.height = height;
    }

    return true;
}

function clearTrackingOverlay() {
    if (!trackingOverlayContext || !trackingOverlay) {
        return;
    }

    trackingOverlayContext.clearRect(0, 0, trackingOverlay.width, trackingOverlay.height);
}

function detectBallPosition(frame) {
    const { data, width, height } = frame;
    let totalX = 0;
    let totalY = 0;
    let matchCount = 0;
    const step = 4;

    for (let y = 0; y < height; y += step) {
        for (let x = 0; x < width; x += step) {
            const index = (y * width + x) * 4;
            const red = data[index];
            const green = data[index + 1];
            const blue = data[index + 2];

            if (red >= TRACKING_COLOR.redMin && green <= TRACKING_COLOR.greenMax && blue <= TRACKING_COLOR.blueMax) {
                totalX += x;
                totalY += y;
                matchCount += 1;
            }
        }
    }

    if (!matchCount) {
        return null;
    }

    return {
        x: totalX / matchCount,
        y: totalY / matchCount
    };
}

function drawTrackingTrail() {
    if (!trackingOverlayContext || !trailPoints.length) {
        return;
    }

    trackingOverlayContext.lineWidth = 4;
    trackingOverlayContext.strokeStyle = "rgba(13, 110, 110, 0.9)";
    trackingOverlayContext.lineJoin = "round";
    trackingOverlayContext.lineCap = "round";
    trackingOverlayContext.beginPath();

    trailPoints.forEach((point, index) => {
        if (index === 0) {
            trackingOverlayContext.moveTo(point.x, point.y);
            return;
        }

        trackingOverlayContext.lineTo(point.x, point.y);
    });

    trackingOverlayContext.stroke();
}

function drawTrackedBall(position) {
    if (!trackingOverlayContext) {
        return;
    }

    trackingOverlayContext.beginPath();
    trackingOverlayContext.arc(position.x, position.y, 12, 0, Math.PI * 2);
    trackingOverlayContext.fillStyle = "rgba(191, 139, 48, 0.28)";
    trackingOverlayContext.fill();
    trackingOverlayContext.lineWidth = 3;
    trackingOverlayContext.strokeStyle = "#bf8b30";
    trackingOverlayContext.stroke();
}

function renderTrackingFrame(position) {
    clearTrackingOverlay();

    if (!position) {
        return;
    }

    trailPoints.push(position);

    if (trailPoints.length > MAX_TRAIL_POINTS) {
        trailPoints.shift();
    }

    drawTrackingTrail();
    drawTrackedBall(position);
}

function runTrackingLoop(timestamp = 0) {
    if (!trackingEnabled || !replayVideo || replayVideo.paused || replayVideo.ended) {
        trackingFrameId = null;
        return;
    }

    if (!syncTrackingCanvasSize()) {
        trackingFrameId = requestAnimationFrame(runTrackingLoop);
        return;
    }

    if (timestamp - lastTrackingTimestamp >= TRACKING_FRAME_INTERVAL) {
        lastTrackingTimestamp = timestamp;
        hiddenTrackingContext.drawImage(replayVideo, 0, 0, hiddenTrackingCanvas.width, hiddenTrackingCanvas.height);
        const frame = hiddenTrackingContext.getImageData(0, 0, hiddenTrackingCanvas.width, hiddenTrackingCanvas.height);
        const position = detectBallPosition(frame);
        renderTrackingFrame(position);
    }

    trackingFrameId = requestAnimationFrame(runTrackingLoop);
}

function beginTrackingLoop() {
    if (!trackingEnabled || trackingFrameId !== null) {
        return;
    }

    lastTrackingTimestamp = 0;
    trackingFrameId = requestAnimationFrame(runTrackingLoop);
}

function startTracking() {
    if (!replayVideo) {
        return;
    }

    if (!ensureTrackingContexts()) {
        showFeedback("Tracking overlay could not be started on this browser.", "error");
        return;
    }

    trackingEnabled = true;
    trailPoints = [];
    clearTrackingOverlay();
    updateReplayStatus("Tracking enabled");
    showFeedback("Ball tracking started. Use a bright red ball for best results.", "success");

    if (!replayVideo.paused && !replayVideo.ended) {
        beginTrackingLoop();
    }
}

function stopTracking() {
    trackingEnabled = false;

    if (trackingFrameId !== null) {
        cancelAnimationFrame(trackingFrameId);
        trackingFrameId = null;
    }

    trailPoints = [];
    clearTrackingOverlay();
    updateReplayStatus(cameraStream ? "Camera is live" : "Tracking stopped");
    showFeedback("Ball tracking stopped.", "warning");
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

    if (trackingEnabled) {
        trailPoints = [];
        clearTrackingOverlay();
    }
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
    if (!(await ensureReplayAllowed())) {
        return;
    }

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
        beginTrackingLoop();
    } catch (error) {
        console.error(error);
        updateReplayStatus("Camera permission denied");
        showFeedback("Camera access was denied or unavailable on this device.", "error");
    }
}

async function startRecording() {
    if (!(await ensureReplayAllowed())) {
        return;
    }

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
    if (!(await ensureReplayAllowed())) {
        return;
    }

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
        if (trackingEnabled) {
            trailPoints = [];
            beginTrackingLoop();
        }
    } catch (error) {
        console.error(error);
        showFeedback("Replay could not start automatically. Use the video controls to play it.", "warning");
    }
}

async function ensureReplayAllowed() {
    if (replayAllowedCache === true) {
        return true;
    }

    const res = await fetch("/replay/access");
    const data = await res.json();

    if (!res.ok || data.ok === false) {
        replayAllowedCache = false;
        updateReplayStatus("Replay locked");
        showFeedback(data.message || "Replay available only in Pro plan.", "warning");
        return false;
    }

    replayAllowedCache = true;
    return true;
}

if (replayVideo) {
    replayVideo.addEventListener("play", () => {
        if (trackingEnabled) {
            beginTrackingLoop();
        }
    });

    replayVideo.addEventListener("pause", () => {
        if (trackingFrameId !== null) {
            cancelAnimationFrame(trackingFrameId);
            trackingFrameId = null;
        }
    });

    replayVideo.addEventListener("ended", () => {
        if (trackingFrameId !== null) {
            cancelAnimationFrame(trackingFrameId);
            trackingFrameId = null;
        }

        if (!cameraStream || mediaRecorder?.state === "recording") {
            return;
        }

        setLivePreview();
        replayVideo.play().catch(() => {});
        updateReplayStatus(trackingEnabled ? "Tracking enabled" : "Camera is live");
    });

    replayVideo.addEventListener("loadedmetadata", () => {
        syncTrackingCanvasSize();
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

async function markPresentBulk() {
    if (!bulkPresentNamesInput) {
        return;
    }

    const players = bulkPresentNamesInput.value.trim();
    if (!players) {
        showFeedback("Enter player names separated by commas.", "warning");
        bulkPresentNamesInput.focus();
        return;
    }

    const body = new URLSearchParams();
    body.append("players", players);

    const res = await fetch("/mark_present_bulk", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString()
    });
    const data = await res.json();

    if (!res.ok) {
        showFeedback(data.message || "Could not mark bulk attendance.", "error");
        return;
    }

    showFeedback(data.message || "Bulk attendance marked.", "success");
    bulkPresentNamesInput.value = "";
    await loadAttendance();
    await loadPlayers();
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

function renderPlayers(players) {
    if (!playerList) {
        return;
    }

    if (!players.length) {
        playerList.innerHTML = `<p class="status-value">No players added yet.</p>`;
        return;
    }

    playerList.innerHTML = players.map((player) => `
        <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.08);">
            <span class="status-value">${escapeHtml(player.name)}</span>
            <div class="button-row" style="margin:0;">
                <button class="secondary-btn" onclick="markPlayerAttendance(${player.id}, 'present')">Present</button>
                <button class="secondary-btn" onclick="markPlayerAttendance(${player.id}, 'late')">Late</button>
                <button class="danger-btn" onclick="deletePlayer(${player.id})">Delete</button>
            </div>
        </div>
    `).join("");
}

async function loadPlayers() {
    if (!playerList) {
        return;
    }

    const res = await fetch("/players");
    const data = await res.json();
    renderPlayers(data.players || []);
}

async function unlockPro() {
    if (!upgradeCodeInput) {
        return;
    }

    const code = upgradeCodeInput.value.trim();
    if (!code) {
        showFeedback("Enter an upgrade code.", "warning");
        upgradeCodeInput.focus();
        return;
    }

    const body = new URLSearchParams();
    body.append("code", code);

    const res = await fetch("/upgrade", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString()
    });
    const data = await res.json();

    if (!res.ok) {
        showFeedback(data.message || "Upgrade failed.", "error");
        return;
    }

    showFeedback(data.message || "Upgrade successful.", "success");
    upgradeCodeInput.value = "";
}

async function addPlayerFast() {
    if (!playerNameInput) {
        return;
    }

    const name = playerNameInput.value.trim();
    if (!name) {
        showFeedback("Enter a player name.", "warning");
        playerNameInput.focus();
        return;
    }

    const body = new URLSearchParams();
    body.append("name", name);

    const res = await fetch("/add_player", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString()
    });
    const data = await res.json();

    if (!res.ok) {
        showFeedback(data.message || "Could not add player.", "error");
        return;
    }

    showFeedback(data.message || "Player added.", "success");
    playerNameInput.value = "";
    await loadPlayers();
}

async function deletePlayer(playerId) {
    const body = new URLSearchParams();
    body.append("id", String(playerId));

    const res = await fetch("/delete_player", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString()
    });
    const data = await res.json();

    if (!res.ok) {
        showFeedback(data.message || "Could not delete player.", "error");
        return;
    }

    showFeedback(data.message || "Player deleted.", "success");
    await loadPlayers();
}

async function markPlayerAttendance(playerId, status) {
    const body = new URLSearchParams();
    body.append("player_id", String(playerId));
    body.append("status", status);

    const res = await fetch("/mark_attendance", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString()
    });
    const data = await res.json();

    if (!res.ok) {
        showFeedback(data.message || "Attendance mark failed.", "error");
        return;
    }

    showFeedback(data.message || "Attendance marked.", "success");
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

if (playerList) {
    loadPlayers();
}
