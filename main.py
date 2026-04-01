from __future__ import annotations

import argparse
import time
from typing import Dict, Generator, Optional, Tuple

import cv2
import numpy as np

from detector import BallDetector
from tracker import KalmanBallTracker, TrackState


class BallTrackingEngine:
    """
    Real-time cricket ball tracking engine.
    - Detector: color + motion + contour + optional Hough validation
    - Tracker: Kalman smoothing and prediction across missed frames
    - Visuals: ball circle, trail, predicted dotted path, confidence, speed
    """

    def __init__(
        self,
        processing_width: int = 960,
        trail_size: int = 20,
        history_size: int = 40,
        max_missing_frames: int = 8,
        pixel_per_meter: Optional[float] = None,
    ) -> None:
        self.processing_width = max(320, processing_width)
        self.detector = BallDetector()
        self.tracker = KalmanBallTracker(
            max_trail=trail_size,
            max_history=history_size,
            max_missing_frames=max_missing_frames,
            pixel_per_meter=pixel_per_meter,
        )

        self.prev_time = time.perf_counter()
        self.fps_smooth = 0.0

    def process_frame(self, frame_bgr: np.ndarray) -> Tuple[np.ndarray, Dict[str, object]]:
        start = time.perf_counter()
        proc_frame, scale = self._resize_for_speed(frame_bgr)

        dt = max(start - self.prev_time, 1e-3)
        self.prev_time = start

        predicted_center = None
        if self.tracker.is_initialized:
            predicted = self.tracker.kf.predict()
            predicted_center = (float(predicted[0, 0]), float(predicted[1, 0]))

        detection, _debug = self.detector.detect(proc_frame, predicted_center=predicted_center)
        state = self.tracker.update(detection, dt=dt)

        annotated_small = self._draw_overlay(proc_frame, state)
        annotated = self._restore_size(annotated_small, scale, frame_bgr.shape[:2])

        frame_time = max(time.perf_counter() - start, 1e-6)
        fps_now = 1.0 / frame_time
        self.fps_smooth = fps_now if self.fps_smooth == 0.0 else (0.92 * self.fps_smooth + 0.08 * fps_now)

        telemetry = self._build_telemetry(state, float(self.fps_smooth), scale)
        return annotated, telemetry

    def _resize_for_speed(self, frame: np.ndarray) -> Tuple[np.ndarray, float]:
        h, w = frame.shape[:2]
        if w <= self.processing_width:
            return frame, 1.0
        scale = self.processing_width / float(w)
        resized = cv2.resize(frame, (self.processing_width, int(h * scale)), interpolation=cv2.INTER_LINEAR)
        return resized, scale

    def _restore_size(self, frame_small: np.ndarray, scale: float, original_shape: Tuple[int, int]) -> np.ndarray:
        if scale == 1.0:
            return frame_small
        oh, ow = original_shape
        return cv2.resize(frame_small, (ow, oh), interpolation=cv2.INTER_LINEAR)

    def _draw_overlay(self, frame: np.ndarray, state: Optional[TrackState]) -> np.ndarray:
        out = frame.copy()

        if state is not None:
            cx, cy = int(state.center[0]), int(state.center[1])
            rr = max(3, int(state.radius))

            color = (0, 200, 255) if not state.is_predicted else (0, 165, 255)
            cv2.circle(out, (cx, cy), rr, color, 2)
            cv2.circle(out, (cx, cy), 2, (255, 255, 255), -1)

            trail = self.tracker.get_trail_points()
            for i in range(1, len(trail)):
                alpha = i / max(len(trail), 1)
                line_color = (int(40 + 160 * alpha), int(100 + 110 * alpha), int(255 - 120 * alpha))
                cv2.line(out, trail[i - 1], trail[i], line_color, 2)

            for i, p in enumerate(state.predicted_path):
                if i % 2 == 0:
                    cv2.circle(out, p, 2, (110, 255, 110), -1)
                if i > 0:
                    cv2.line(out, state.predicted_path[i - 1], p, (90, 220, 90), 1, lineType=cv2.LINE_AA)

            label = f"Conf: {state.confidence:.2f}"
            cv2.putText(out, label, (cx + 12, cy - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

            if state.speed_mps is not None:
                cv2.putText(
                    out,
                    f"Speed: {state.speed_mps:.1f} m/s",
                    (15, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 255),
                    2,
                )

            if state.bounce_point is not None:
                bx, by = int(state.bounce_point[0]), int(state.bounce_point[1])
                cv2.circle(out, (bx, by), 6, (255, 100, 100), 2)
                cv2.putText(out, "Bounce", (bx + 8, by - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 120, 120), 1)

        cv2.putText(out, f"FPS: {self.fps_smooth:.1f}", (15, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (120, 255, 120), 2)
        return out

    def _build_telemetry(self, state: Optional[TrackState], fps: float, scale: float) -> Dict[str, object]:
        if state is None:
            return {
                "tracked": False,
                "fps": fps,
                "confidence": 0.0,
                "speed_mps": None,
                "bounce_point": None,
                "line_prediction_x": None,
            }

        # Convert small-frame coordinates to original scale for API users.
        inv = 1.0 / scale
        center = (state.center[0] * inv, state.center[1] * inv)
        bounce = (
            (state.bounce_point[0] * inv, state.bounce_point[1] * inv)
            if state.bounce_point is not None
            else None
        )
        line_prediction_x = self.tracker.predict_line_at_y(target_y=state.center[1])
        line_prediction_x = line_prediction_x * inv if line_prediction_x is not None else None

        return {
            "tracked": True,
            "center": center,
            "radius": state.radius * inv,
            "confidence": state.confidence,
            "predicted": state.is_predicted,
            "fps": fps,
            "speed_mps": state.speed_mps,
            "bounce_point": bounce,
            "line_prediction_x": line_prediction_x,
        }


def run_video(source: str = "0", display: bool = True, save_path: Optional[str] = None) -> None:
    source_index_or_path = int(source) if source.isdigit() else source
    cap = cv2.VideoCapture(source_index_or_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open source: {source}")

    engine = BallTrackingEngine(processing_width=960, max_missing_frames=10)

    writer = None
    if save_path:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1280)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 720)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(save_path, fourcc, fps, (width, height))

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            annotated, telemetry = engine.process_frame(frame)
            _ = telemetry

            if writer is not None:
                writer.write(annotated)

            if display:
                cv2.imshow("TrainEdge Ball Tracking", annotated)
                key = cv2.waitKey(1) & 0xFF
                if key == 27 or key == ord("q"):
                    break
    finally:
        cap.release()
        if writer is not None:
            writer.release()
        if display:
            cv2.destroyAllWindows()


def generate_mjpeg_frames(source: int = 0) -> Generator[bytes, None, None]:
    """
    Flask integration helper.
    Example:
        return Response(generate_mjpeg_frames(0), mimetype="multipart/x-mixed-replace; boundary=frame")
    """
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        return

    engine = BallTrackingEngine(processing_width=800, max_missing_frames=10)
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            annotated, _telemetry = engine.process_frame(frame)
            ok_jpeg, buffer = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if not ok_jpeg:
                continue
            jpg = buffer.tobytes()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpg + b"\r\n"
            )
    finally:
        cap.release()


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TrainEdge real-time cricket ball tracking")
    parser.add_argument("--source", type=str, default="0", help="Camera index (0/1) or video file path")
    parser.add_argument("--save", type=str, default=None, help="Optional output video path (.mp4)")
    parser.add_argument("--no-display", action="store_true", help="Run without on-screen preview")
    return parser


if __name__ == "__main__":
    args = _build_arg_parser().parse_args()
    run_video(source=args.source, display=not args.no_display, save_path=args.save)

