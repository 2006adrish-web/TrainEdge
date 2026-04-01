from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Tuple

import cv2
import numpy as np

from detector import BallDetection


@dataclass
class TrackState:
    center: Tuple[float, float]
    radius: float
    confidence: float
    is_predicted: bool
    speed_mps: Optional[float]
    bounce_point: Optional[Tuple[float, float]]
    predicted_path: List[Tuple[int, int]]


class KalmanBallTracker:
    """
    Constant-velocity Kalman tracker with:
    - measurement correction from detector
    - prediction during temporary misses
    - smoothed trail and quadratic path forecast
    """

    def __init__(
        self,
        max_trail: int = 20,
        max_history: int = 40,
        max_missing_frames: int = 8,
        fps: float = 30.0,
        pixel_per_meter: Optional[float] = None,
    ) -> None:
        self.kf = cv2.KalmanFilter(4, 2)
        self.kf.measurementMatrix = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], np.float32)
        self.kf.transitionMatrix = np.array(
            [[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]],
            np.float32,
        )
        self.kf.processNoiseCov = np.eye(4, dtype=np.float32) * 1e-2
        self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 8e-2
        self.kf.errorCovPost = np.eye(4, dtype=np.float32)

        self.is_initialized = False
        self.last_radius = 6.0
        self.missing_frames = 0
        self.max_missing_frames = max_missing_frames

        self.trail: Deque[Tuple[float, float]] = deque(maxlen=max_trail)
        self.history: Deque[Tuple[float, float]] = deque(maxlen=max_history)

        self.fps = max(fps, 1.0)
        self.pixel_per_meter = pixel_per_meter

    def update(self, detection: Optional[BallDetection], dt: float = 1.0) -> Optional[TrackState]:
        self._set_dt(dt)

        predicted_state = self.kf.predict()
        pred_x = float(predicted_state[0, 0])
        pred_y = float(predicted_state[1, 0])

        if detection is not None:
            measurement = np.array([[np.float32(detection.center[0])], [np.float32(detection.center[1])]])
            if not self.is_initialized:
                self.kf.statePost = np.array(
                    [[measurement[0, 0]], [measurement[1, 0]], [0.0], [0.0]],
                    dtype=np.float32,
                )
                self.is_initialized = True

            corrected = self.kf.correct(measurement)
            center = (float(corrected[0, 0]), float(corrected[1, 0]))
            self.last_radius = detection.radius
            self.missing_frames = 0
            base_confidence = float(detection.confidence)
            is_predicted = False
        else:
            if not self.is_initialized:
                return None
            self.missing_frames += 1
            if self.missing_frames > self.max_missing_frames:
                return None
            center = (pred_x, pred_y)
            base_confidence = max(0.2, 0.9 - 0.12 * self.missing_frames)
            is_predicted = True

        self.trail.append(center)
        self.history.append(center)

        speed_mps = self._estimate_speed_mps()
        bounce_point = self._estimate_bounce_point()
        predicted_path = self._predict_future_path(steps=14, step_dt=dt)
        confidence = float(np.clip(base_confidence - 0.05 * self.missing_frames, 0.0, 1.0))

        return TrackState(
            center=center,
            radius=float(self.last_radius),
            confidence=confidence,
            is_predicted=is_predicted,
            speed_mps=speed_mps,
            bounce_point=bounce_point,
            predicted_path=predicted_path,
        )

    def _set_dt(self, dt: float) -> None:
        frame_dt = float(max(dt, 1e-3))
        self.kf.transitionMatrix = np.array(
            [[1, 0, frame_dt, 0], [0, 1, 0, frame_dt], [0, 0, 1, 0], [0, 0, 0, 1]],
            dtype=np.float32,
        )

    def get_trail_points(self) -> List[Tuple[int, int]]:
        return [(int(x), int(y)) for x, y in self.trail]

    def _estimate_speed_mps(self) -> Optional[float]:
        if self.pixel_per_meter is None or len(self.history) < 2:
            return None
        x1, y1 = self.history[-2]
        x2, y2 = self.history[-1]
        pixel_dist = float(np.hypot(x2 - x1, y2 - y1))
        meters = pixel_dist / max(self.pixel_per_meter, 1e-6)
        return meters * self.fps

    def _estimate_bounce_point(self) -> Optional[Tuple[float, float]]:
        if len(self.history) < 7:
            return None

        points = list(self.history)[-12:]
        ys = [p[1] for p in points]
        xs = [p[0] for p in points]

        # Bounce in image coordinates is approximated by a local extremum in Y.
        for i in range(2, len(ys) - 2):
            dy1 = ys[i] - ys[i - 1]
            dy2 = ys[i + 1] - ys[i]
            if dy1 > 0 and dy2 < 0:
                return (xs[i], ys[i])
            if dy1 < 0 and dy2 > 0:
                return (xs[i], ys[i])
        return None

    def _predict_future_path(self, steps: int = 12, step_dt: float = 1.0) -> List[Tuple[int, int]]:
        if len(self.history) < 5:
            return []

        points = np.array(self.history, dtype=np.float32)
        t = np.arange(len(points), dtype=np.float32)
        xs = points[:, 0]
        ys = points[:, 1]

        try:
            coef_x = np.polyfit(t, xs, 2)
            coef_y = np.polyfit(t, ys, 2)
        except np.linalg.LinAlgError:
            return []

        future = []
        t_last = t[-1]
        for i in range(1, steps + 1):
            tf = t_last + i * max(step_dt, 1.0)
            px = float(coef_x[0] * tf * tf + coef_x[1] * tf + coef_x[2])
            py = float(coef_y[0] * tf * tf + coef_y[1] * tf + coef_y[2])
            future.append((int(px), int(py)))
        return future

    def predict_line_at_y(self, target_y: float) -> Optional[float]:
        """
        Approximate x at given y, useful for LBW-style line projection.
        """
        if len(self.history) < 5:
            return None

        points = np.array(self.history, dtype=np.float32)
        x = points[:, 0]
        y = points[:, 1]

        try:
            coeff = np.polyfit(y, x, 1)
        except np.linalg.LinAlgError:
            return None

        return float(coeff[0] * target_y + coeff[1])

