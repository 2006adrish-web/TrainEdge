from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import cv2
import numpy as np


@dataclass
class BallDetection:
    center: Tuple[int, int]
    radius: float
    confidence: float
    circularity: float
    area: float


class BallDetector:
    """
    Cricket ball detector using:
    - HSV color filtering (with adaptive local refinement)
    - Motion gating from frame differencing
    - Contour circularity scoring
    - Optional Hough validation
    """

    def __init__(self) -> None:
        # Conservative defaults for a red cricket ball; adjusted adaptively per frame.
        self.lower_red_1 = np.array([0, 70, 40], dtype=np.uint8)
        self.upper_red_1 = np.array([12, 255, 255], dtype=np.uint8)
        self.lower_red_2 = np.array([160, 70, 40], dtype=np.uint8)
        self.upper_red_2 = np.array([179, 255, 255], dtype=np.uint8)

        self.prev_gray: Optional[np.ndarray] = None
        self.min_area = 20
        self.max_area = 4500
        self.min_circularity = 0.45
        self.use_hough_validation = True

    def detect(
        self,
        frame_bgr: np.ndarray,
        predicted_center: Optional[Tuple[float, float]] = None,
    ) -> Tuple[Optional[BallDetection], Dict[str, np.ndarray]]:
        blurred = cv2.GaussianBlur(frame_bgr, (5, 5), 0)
        hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(blurred, cv2.COLOR_BGR2GRAY)

        color_mask = self._build_color_mask(hsv, predicted_center)
        motion_mask = self._build_motion_mask(gray)
        combined_mask = self._combine_masks(color_mask, motion_mask)

        contours, _ = cv2.findContours(combined_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detection = self._best_contour_detection(contours, gray)

        self.prev_gray = gray

        debug = {
            "color_mask": color_mask,
            "motion_mask": motion_mask,
            "combined_mask": combined_mask,
        }
        return detection, debug

    def _build_color_mask(
        self,
        hsv: np.ndarray,
        predicted_center: Optional[Tuple[float, float]],
    ) -> np.ndarray:
        base_mask = cv2.inRange(hsv, self.lower_red_1, self.upper_red_1)
        base_mask |= cv2.inRange(hsv, self.lower_red_2, self.upper_red_2)

        adaptive_mask = np.zeros_like(base_mask)
        if predicted_center is not None:
            px, py = int(predicted_center[0]), int(predicted_center[1])
            h, w = hsv.shape[:2]
            roi_half = 35
            x1 = max(0, px - roi_half)
            y1 = max(0, py - roi_half)
            x2 = min(w, px + roi_half)
            y2 = min(h, py + roi_half)
            if x2 > x1 and y2 > y1:
                roi = hsv[y1:y2, x1:x2]
                adaptive_mask = self._adaptive_hsv_mask(roi, hsv)

        mask = cv2.bitwise_or(base_mask, adaptive_mask)

        # Noise reduction
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        mask = cv2.erode(mask, kernel, iterations=1)
        mask = cv2.dilate(mask, kernel, iterations=2)
        return mask

    def _adaptive_hsv_mask(self, roi: np.ndarray, full_hsv: np.ndarray) -> np.ndarray:
        # Keep only reasonably saturated pixels to avoid adapting to background.
        sat = roi[:, :, 1]
        val = roi[:, :, 2]
        valid = (sat > 50) & (val > 40)
        if np.count_nonzero(valid) < 20:
            return np.zeros(full_hsv.shape[:2], dtype=np.uint8)

        roi_h = roi[:, :, 0][valid]
        roi_s = sat[valid]
        roi_v = val[valid]

        h_center = int(np.median(roi_h))
        h_delta = max(10, int(np.std(roi_h) * 2 + 8))
        s_low = max(40, int(np.percentile(roi_s, 15) - 20))
        v_low = max(25, int(np.percentile(roi_v, 15) - 20))

        lower = np.array([max(0, h_center - h_delta), s_low, v_low], dtype=np.uint8)
        upper = np.array([min(179, h_center + h_delta), 255, 255], dtype=np.uint8)

        if lower[0] <= upper[0]:
            return cv2.inRange(full_hsv, lower, upper)

        # Hue wrap-around case
        lower_a = np.array([0, s_low, v_low], dtype=np.uint8)
        upper_a = np.array([upper[0], 255, 255], dtype=np.uint8)
        lower_b = np.array([lower[0], s_low, v_low], dtype=np.uint8)
        upper_b = np.array([179, 255, 255], dtype=np.uint8)
        return cv2.inRange(full_hsv, lower_a, upper_a) | cv2.inRange(full_hsv, lower_b, upper_b)

    def _build_motion_mask(self, gray: np.ndarray) -> np.ndarray:
        if self.prev_gray is None:
            return np.full(gray.shape, 255, dtype=np.uint8)

        diff = cv2.absdiff(gray, self.prev_gray)
        diff = cv2.GaussianBlur(diff, (5, 5), 0)
        _, motion = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        motion = cv2.dilate(motion, np.ones((3, 3), np.uint8), iterations=2)
        return motion

    def _combine_masks(self, color_mask: np.ndarray, motion_mask: np.ndarray) -> np.ndarray:
        combined = cv2.bitwise_and(color_mask, motion_mask)
        moving_pixels = int(np.count_nonzero(motion_mask))

        # Fallback to color-only if the motion mask is too weak or camera is mostly static blur.
        if moving_pixels < 25:
            combined = color_mask.copy()

        combined = cv2.medianBlur(combined, 5)
        return combined

    def _best_contour_detection(
        self,
        contours: list[np.ndarray],
        gray_frame: np.ndarray,
    ) -> Optional[BallDetection]:
        best: Optional[BallDetection] = None
        best_score = 0.0

        for contour in contours:
            area = cv2.contourArea(contour)
            if area < self.min_area or area > self.max_area:
                continue

            perimeter = cv2.arcLength(contour, True)
            if perimeter <= 0.0:
                continue

            circularity = float((4.0 * np.pi * area) / (perimeter * perimeter))
            if circularity < self.min_circularity:
                continue

            (x, y), radius = cv2.minEnclosingCircle(contour)
            if radius < 2.0 or radius > 50.0:
                continue

            confidence = self._score_candidate(circularity, area, radius)
            if self.use_hough_validation:
                confidence += self._hough_bonus(gray_frame, (int(x), int(y)), radius)
            confidence = float(min(confidence, 1.0))

            if confidence > best_score:
                best_score = confidence
                best = BallDetection(
                    center=(int(x), int(y)),
                    radius=float(radius),
                    confidence=confidence,
                    circularity=float(circularity),
                    area=float(area),
                )
        return best

    def _score_candidate(self, circularity: float, area: float, radius: float) -> float:
        area_from_radius = np.pi * radius * radius
        fill_ratio = min(area / (area_from_radius + 1e-6), 1.0)
        c_score = np.clip((circularity - self.min_circularity) / (1.0 - self.min_circularity), 0.0, 1.0)
        a_score = np.clip(fill_ratio, 0.0, 1.0)
        return float(0.65 * c_score + 0.35 * a_score)

    def _hough_bonus(self, gray: np.ndarray, center: Tuple[int, int], radius: float) -> float:
        x, y = center
        h, w = gray.shape[:2]
        pad = int(max(20, radius * 3))
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(w, x + pad)
        y2 = min(h, y + pad)
        roi = gray[y1:y2, x1:x2]
        if roi.size == 0:
            return 0.0

        circles = cv2.HoughCircles(
            roi,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=max(8, int(radius)),
            param1=100,
            param2=12,
            minRadius=max(2, int(radius * 0.5)),
            maxRadius=max(6, int(radius * 1.8)),
        )
        return 0.15 if circles is not None else 0.0

