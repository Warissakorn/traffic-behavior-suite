from copy import deepcopy
import json
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
import yaml
from ..config import load_site


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name+".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


class SiteDocument:
    def __init__(self):
        self.path = None
        self.config = {"schema_version": 1, "site_id": "site_A", "epoch": datetime.now(timezone(timedelta(hours=7))).isoformat(timespec="seconds"),
                       "videos": [], "camera": {"model_file": ""}, "road": {"count_lines": []},
                       "models": {"detector": ""}, "options": {"device": "cpu", "confidence": 0.25, "resample_dt": 0.1}}

    def open(self, path):
        path = Path(path).resolve()
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or config.get("schema_version") != 1:
            raise ValueError("รองรับ site schema_version 1 เท่านั้น")
        config = deepcopy(config)
        for clip in config.get("videos", []):
            clip["path"] = str((path.parent/clip["path"]).resolve())
        for section, key in [("camera", "model_file"), ("models", "detector"), ("models", "reid")]:
            value = config.get(section, {}).get(key)
            if value and value != "synthetic_color":
                config[section][key] = str((path.parent/value).resolve())
        self.path, self.config = path, config

    def save(self, path):
        path = Path(path).resolve()
        config = deepcopy(self.config)
        def relative(value):
            if not value or value == "synthetic_color":
                return value
            absolute = Path(value).resolve()
            try:
                return os.path.relpath(absolute, path.parent).replace("\\", "/")
            except ValueError:  # different Windows drives
                return str(absolute)
        for clip in config.get("videos", []):
            clip["path"] = relative(clip["path"])
        for section, key in [("camera", "model_file"), ("models", "detector"), ("models", "reid")]:
            if key in config.get(section, {}):
                config[section][key] = relative(config[section][key])
        atomic_text(path, yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
        self.path = path

    def snapshot(self, path):
        atomic_text(path, yaml.safe_dump(self.config, allow_unicode=True, sort_keys=False))
        return str(path)

    def validate(self, temporary_path):
        return load_site(self.snapshot(temporary_path))
