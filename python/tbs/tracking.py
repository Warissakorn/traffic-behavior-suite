"""Baseline ground-plane association; intended for validation before improvement."""
import numpy as np
from scipy.optimize import linear_sum_assignment


class Tracker:
    def __init__(self, max_distance=3.0, max_gap=0.5):
        self.max_distance, self.max_gap = max_distance, max_gap
        self.active, self.next_id = {}, 1

    def update(self, t, detections):
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
                velocity = np.zeros(2)
            else:
                old = self.active[key]
                velocity = (det["xy"]-old["xy"])/(t-old["t"])
            self.active[key] = {"t": t, "xy": det["xy"], "velocity": velocity, "class_id": det["class_id"]}
            result.append(key)
        return result
