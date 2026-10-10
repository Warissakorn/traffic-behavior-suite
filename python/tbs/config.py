"""Validated site configuration; relative paths are relative to the YAML file."""
from datetime import datetime
from importlib.resources import files
from pathlib import Path
import json
import numpy as np
import yaml
from jsonschema import Draft202012Validator, FormatChecker


def timestamp(value):
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("start_time/epoch must include a timezone")
    return dt.timestamp()


def load_site(path):
    path = Path(path).resolve()
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema = json.loads(files("tbs").joinpath("schemas/site.json").read_text())
    errors = sorted(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(config), key=lambda e: str(e.path))
    if errors:
        raise ValueError("; ".join(f"{'.'.join(map(str, e.path)) or 'config'}: {e.message}" for e in errors))
    for video in config["videos"]:
        timestamp(video["start_time"])
        video["path"] = str((path.parent / video["path"]).resolve())
        if not Path(video["path"]).is_file():
            raise ValueError(f"Video not found: {video['path']}")
    if "epoch" in config:
        timestamp(config["epoch"])
    else:
        config["epoch"] = config["videos"][0]["start_time"]
    camera_path = (path.parent / config["camera"]["model_file"]).resolve()
    camera = yaml.safe_load(camera_path.read_text(encoding="utf-8"))
    # Phase 0 reference supports a planar, already-undistorted camera only.
    if not isinstance(camera, dict) or camera.get("projection") != "planar_homography":
        raise ValueError("camera projection must be planar_homography")
    h = np.asarray(camera.get("image_to_ground"), dtype=float)
    if h.shape != (3, 3) or not np.isfinite(h).all() or abs(np.linalg.det(h)) < 1e-12:
        raise ValueError("image_to_ground must be a finite, invertible 3x3 matrix")
    config["camera"]["model_file"] = str(camera_path)
    config["camera"]["image_to_ground"] = h.tolist()
    detector = config["models"]["detector"]
    if detector != "synthetic_color":
        model = (path.parent / detector).resolve()
        if not model.is_file():
            raise ValueError(f"Detector model not found: {model}")
        config["models"]["detector"] = str(model)
    road = config["road"]
    for key in ("lanes", "count_lines"):
        ids = [item["id"] for item in road.get(key, [])]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate {key} IDs")
    for line in road["count_lines"]:
        if line["p1"] == line["p2"]:
            raise ValueError(f"Zero-length count line: {line['id']}")
    if road.get("zones"):
        raise ValueError("OD zones are not supported by the Foundation pipeline yet")
    config.setdefault("options", {})
    return config


def load_project(path):
    path = Path(path).resolve()
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema = json.loads(files("tbs").joinpath("schemas/project.json").read_text())
    errors = list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(config))
    if errors:
        raise ValueError("; ".join(e.message for e in errors))
    timestamp(config["epoch"])
    ids = [site["id"] for site in config["sites"]]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate site IDs in project")
    for site in config["sites"]:
        site_path = (path.parent/site["config"]).resolve()
        resolved = load_site(site_path)
        if resolved["site_id"] != site["id"]:
            raise ValueError("Project site ID does not match site config")
        if timestamp(resolved["epoch"]) != timestamp(config["epoch"]):
            raise ValueError("Project and site configs must share the same epoch")
        site["config"] = str(site_path)
    edges = set()
    for link in config["links"]:
        edge = (link["from"], link["to"])
        if edge[0] not in ids or edge[1] not in ids or edge[0] == edge[1]:
            raise ValueError("Project link references an unknown site or itself")
        if edge in edges:
            raise ValueError("Duplicate project links")
        edges.add(edge)
    return config
