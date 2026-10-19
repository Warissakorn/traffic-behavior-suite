"""Image ROI membership and directed, finite point-gate passages."""
import math
import cv2
import numpy as np


def validate_regions(regions):
    if regions is None:
        return dict(roi=[], points=[])
    if not isinstance(regions, dict) or set(regions) - {'roi', 'points', 'crop_before_detect'}:
        raise ValueError('image_regions must contain only roi, points and crop_before_detect')
    roi, points = regions.get('roi', []), regions.get('points', [])
    crop = regions.get('crop_before_detect', False)
    if type(crop) is not bool:
        raise ValueError('crop_before_detect must be a boolean')
    if crop and not roi:
        raise ValueError('crop_before_detect requires an ROI; draw the processing rectangle first')
    if not isinstance(roi, list) or (roi and len(roi) != 4):
        raise ValueError('ROI must be four rectangle corners, or an empty list')
    def point(value):
        return (isinstance(value, (list, tuple)) and len(value) == 2 and
                all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in value))
    if any(not point(p) for p in roi):
        raise ValueError('ROI coordinates must be finite nonnegative image pixels')
    if roi:
        a = np.asarray(roi, dtype=float)
        x1, y1 = a.min(axis=0)
        x2, y2 = a.max(axis=0)
        expected = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]])
        if x2 <= x1 or y2 <= y1 or not np.allclose(a, expected):
            raise ValueError('ROI must be a nonzero rectangle ordered top-left, top-right, bottom-right, bottom-left')
    if not isinstance(points, list) or len(points) > 100:
        raise ValueError('Expected up to 100 image point gates')
    ids = set()
    for gate in points:
        if not isinstance(gate, dict) or set(gate) - {'id', 'p1', 'p2', 'direction'}:
            raise ValueError('Invalid point gate')
        key = gate.get('id')
        if not isinstance(key, str) or not key.strip() or key in ids:
            raise ValueError('Point gate IDs must be nonempty and unique')
        ids.add(key)
        if not point(gate.get('p1')) or not point(gate.get('p2')) or gate['p1'] == gate['p2']:
            raise ValueError('Point gate requires two distinct finite pixel coordinates')
        if type(gate.get('direction', 0)) is not int or gate.get('direction', 0) not in (-1, 0, 1):
            raise ValueError('Point gate direction must be -1, 0 (both) or 1')
    result = dict(roi=roi, points=points)
    if 'crop_before_detect' in regions:
        result['crop_before_detect'] = crop
    return result


class Regions:
    def __init__(self, config=None):
        self.config = validate_regions(config)
        self.roi = np.asarray(self.config['roi'], np.float32)
        self.shape = None
        self.inference = None

    def check_image(self, image):
        shape = image.shape[:2]
        if shape == self.shape:
            return
        if self.shape is not None and (self.config['roi'] or self.config['points']):
            raise ValueError('Video resolution changed; ROI/point gates require the same image dimensions across clips')
        height, width = shape
        coordinates = list(self.config['roi'])
        for gate in self.config['points']:
            coordinates += [gate['p1'], gate['p2']]
        if any(x > width or y > height for x, y in coordinates):
            raise ValueError('ROI/point gate lies outside the video frame; redraw for this resolution')
        self.shape = shape

    def contains(self, x, y):
        return not self.roi.size or cv2.pointPolygonTest(self.roi, (float(x), float(y)), False) >= 0

    def filter(self, detections, image):
        self.check_image(image)
        return [det for det in detections if self.contains((det[2]+det[4])/2, det[5])]

    def detect(self, detector, image):
        """Infer on an optional crop, then restore full-frame coordinates."""
        self.check_image(image)
        height, width = image.shape[:2]
        crop = self.config.get('crop_before_detect', False)
        if crop:
            # Outward rounding includes every pixel touched by fractional ROI bounds.
            bounds = np.asarray(self.config['roi'], dtype=float)
            x1, y1 = np.floor(bounds.min(axis=0)).astype(int)
            x2, y2 = np.ceil(bounds.max(axis=0)).astype(int)
            x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
            if x2 <= x1 or y2 <= y1:
                raise ValueError('ROI crop contains no image pixels')
            source = np.ascontiguousarray(image[y1:y2, x1:x2])
        else:
            x1, y1, x2, y2 = 0, 0, width, height
            source = image
        self.inference = dict(mode='roi_crop' if crop else 'full_frame', coordinate_space='full_frame',
                              frame_size=[width, height], detector_input_size=[x2-x1, y2-y1],
                              crop_box_xyxy=[int(x1), int(y1), int(x2), int(y2)])
        # Use Python numbers so metadata and coordinates are JSON serializable.
        self.inference['detector_input_size'] = list(map(int, self.inference['detector_input_size']))
        detections = detector.detect(source)
        if crop:
            detections = [(cls, score, float(a+x1), float(b+y1), float(c+x1), float(d+y1))
                          for cls, score, a, b, c, d in detections]
        return self.filter(detections, image)


class Passages:
    def __init__(self, gates, max_gap=.5):
        self.gates = gates
        self.max_gap = max_gap
        self.active = {}
        self.next_id = 1

    def update(self, t, detections, ids, frame_index):
        self.active = {key: state for key, state in self.active.items() if t-state['last_t'] <= self.max_gap}
        events = []
        for det, vehicle in zip(detections, ids):
            pixel = np.array([(det['x1']+det['x2'])/2, det['y2']], dtype=float)
            state = self.active.setdefault(vehicle, dict(last_t=t, sides={}))
            state['last_t'] = t
            for gate in self.gates:
                a, b = np.array(gate['p1'], float), np.array(gate['p2'], float)
                edge = b-a
                delta = pixel-a
                side = edge[0]*delta[1]-edge[1]*delta[0]
                if abs(side) < 1e-8:
                    continue
                previous = state['sides'].get(gate['id'])
                if previous is not None:
                    old_t, old_pixel, old_side = previous
                    if old_side*side < 0:
                        alpha = old_side/(old_side-side)
                        hit = old_pixel+alpha*(pixel-old_pixel)
                        fraction = np.dot(hit-a, edge)/np.dot(edge, edge)
                        direction = 1 if side > old_side else -1
                        if 0 <= fraction <= 1 and gate.get('direction', 0) in (0, direction):
                            events.append(dict(passage_id=self.next_id, vehicle_id=vehicle, point_id=gate['id'],
                                               t=float(old_t+alpha*(t-old_t)), direction=direction,
                                               frame_index=frame_index))
                            self.next_id += 1
                state['sides'][gate['id']] = (t, pixel, side)
        return events
