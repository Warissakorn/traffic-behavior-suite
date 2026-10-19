"""Ground-plane association with a bounded motion history per vehicle."""
from collections import deque
import numpy as np
from scipy.optimize import linear_sum_assignment


class Tracker:
    def __init__(self, max_distance=3.0, max_gap=0.5, motion_window=5):
        if not np.isfinite(max_distance) or max_distance <= 0 or not np.isfinite(max_gap) or max_gap <= 0:
            raise ValueError("Tracking distance and gap must be finite and positive")
        if type(motion_window) is not int or not 2 <= motion_window <= 30:
            raise ValueError("Tracking motion window must be an integer between 2 and 30")
        self.max_distance, self.max_gap = max_distance, max_gap
        self.motion_window = motion_window
        self.last_t = None
        self.active, self.next_id = {}, 1

    def update(self, t, detections):
        if not np.isfinite(t) or (self.last_t is not None and t <= self.last_t):
            raise ValueError("Tracking timestamps must be finite and strictly increasing")
        # Validate and copy before changing state; callers may reuse detection arrays.
        detections = [dict(det, xy=np.array(det["xy"], dtype=float, copy=True)) for det in detections]
        if any(det["xy"].shape != (2,) or not np.isfinite(det["xy"]).all() for det in detections):
            raise ValueError("Tracking positions must be finite 2D coordinates")
        self.last_t = t
        self.active = {key: value for key, value in self.active.items() if t-value["t"] <= self.max_gap}
        ids = list(self.active)
        assignments = {}
        if ids and detections:
            cost = np.full((len(ids), len(detections)), 1e9)
            for i, key in enumerate(ids):
                track = self.active[key]
                predicted = track["xy"] + track["velocity"] * (t-track["t"])
                for j, det in enumerate(detections):
                    distance = np.linalg.norm(predicted-det["xy"])
                    if track["class_id"] == det["class_id"] and distance <= self.max_distance:
                        cost[i, j] = distance
            rows, cols = linear_sum_assignment(cost)
            assignments = {j: ids[i] for i, j in zip(rows, cols) if cost[i, j] < 1e9}
        result = []
        for j, det in enumerate(detections):
            key = assignments.get(j)
            if key is None:
                key, self.next_id = self.next_id, self.next_id+1
                history = deque(maxlen=self.motion_window)
            else:
                old = self.active[key]
                history = old["history"]
            history.append((t, det["xy"]))
            # Regress on actual observation times, not nominal FPS. Empty frames
            # never become observations. Retaining several samples avoids turning
            # a single jittery detection into a large velocity extrapolation.
            times = np.array([sample[0] - t for sample in history])
            positions = np.array([sample[1] for sample in history])
            centered = times - times.mean()
            if len(history) > 1:
                velocity = (centered @ positions) / (centered @ centered)
                position = positions.mean(axis=0) - times.mean() * velocity
            else:
                velocity, position = np.zeros(2), det["xy"]
            self.active[key] = {"t": t, "xy": position, "velocity": velocity,
                                "class_id": det["class_id"], "history": history}
            result.append(key)
        return result
