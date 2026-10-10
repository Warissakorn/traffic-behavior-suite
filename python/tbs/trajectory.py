"""Reference resampling and finite-line crossings. No RTS claims at this stage."""
import numpy as np
from scipy.signal import savgol_filter


def reconstruct(samples, dt=0.1, max_gap=0.5):
    data = np.asarray(samples, dtype=float)  # t, x, y
    segments = np.split(data, np.where(np.diff(data[:, 0]) > max_gap)[0]+1)
    for segment in segments:
        if len(segment) < 2:
            continue
        times, xy = segment[:, 0], segment[:, 1:]
        if (times[-1]-times[0])/dt > 100000:
            raise ValueError("Resampled track exceeds reference limit of 100000 rows")
        grid = np.arange(times[0], times[-1]+dt*1e-6, dt)
        if len(grid) < 2:
            continue
        points = np.column_stack([np.interp(grid, times, xy[:, axis]) for axis in (0, 1)])
        window = min(7, len(grid) if len(grid) % 2 else len(grid)-1)
        if window >= 5:
            points = savgol_filter(points, window, 2, axis=0)
        velocity = np.gradient(points, grid, axis=0)
        speed = np.linalg.norm(velocity, axis=1)
        accel = np.gradient(speed, grid)
        nearest = np.searchsorted(times, grid)
        right = times[np.minimum(nearest, len(times)-1)]
        left = times[np.maximum(nearest-1, 0)]
        observed = np.minimum(abs(grid-right), abs(grid-left)) <= 1e-7
        yield [dict(t=float(t), x=float(p[0]), y=float(p[1]), v=float(v), a=float(a),
                    heading=float(np.arctan2(vel[1], vel[0])), lane_id=-1, s=None, d=None,
                    leader_id=-1, space_headway=None, time_headway=None, observed=bool(obs), quality=None)
               for t, p, v, a, vel, obs in zip(grid, points, speed, accel, velocity, observed)]


def crossings(rows, lines):
    for line in lines:
        a, b = np.asarray(line["p1"], dtype=float), np.asarray(line["p2"], dtype=float)
        edge = b-a
        previous_nonzero = None
        for row in rows:
            point = np.array([row["x"], row["y"]])
            delta = point-a
            side = edge[0]*delta[1]-edge[1]*delta[0]
            if abs(side) < 1e-9:
                continue  # preserve the last side to handle a sample exactly on the line
            if previous_nonzero is not None:
                old, old_point, old_side = previous_nonzero
                if side*old_side < 0:
                    alpha = old_side/(old_side-side)
                    hit = old_point+alpha*(point-old_point)
                    fraction = np.dot(hit-a, edge)/np.dot(edge, edge)
                    if 0 <= fraction <= 1:
                        yield dict(vehicle_id=row["vehicle_id"], line_id=line["id"],
                                   t=old["t"]+alpha*(row["t"]-old["t"]),
                                   direction=1 if side > old_side else -1, lane_id=-1,
                                   v=old["v"]+alpha*(row["v"]-old["v"]))
            previous_nonzero = row, point, side
