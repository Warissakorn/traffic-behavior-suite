"""Explicit downloads of official Ultralytics assets, verified before use."""
import hashlib
import json
import os
import re
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .models import PRESETS, file_hash

RELEASE_URL = "https://api.github.com/repos/ultralytics/assets/releases/latest"
MAX_BYTES = 2 * 1024**3


def _open(url):
    return urlopen(Request(url, headers={"User-Agent": "TrafficBehaviorSuite/0.1"}), timeout=15)


def download_model(preset, registry, *, progress=lambda done, total: None, cancelled=lambda: False):
    """Keep previous/custom weights; cache each official version by SHA-256.

    No inference or pickle loading occurs here. A missing upstream digest is an
    error, rather than an invitation to skip verification.
    """
    if preset not in PRESETS:
        raise ValueError("เลือกโปรไฟล์ YOLO11 หรือ YOLO26 ก่อนดาวน์โหลด")

    def check_cancelled():
        if cancelled():
            raise ValueError("ยกเลิกการดาวน์โหลดแล้ว")

    check_cancelled()
    with _open(RELEASE_URL) as response:
        raw = response.read(4 * 1024**2 + 1)
    if len(raw) > 4 * 1024**2:
        raise ValueError("ข้อมูลรุ่นโมเดลมีขนาดใหญ่เกินกำหนด")
    release = json.loads(raw)
    filename = PRESETS[preset]["filename"]
    asset = next((a for a in release.get("assets", []) if a.get("name") == filename), None)
    if asset is None:
        raise ValueError(f"ไม่พบ {filename} ใน release ล่าสุดของ Ultralytics")
    digest = asset.get("digest") or ""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("แหล่งดาวน์โหลดไม่มี SHA-256 ที่ตรวจสอบได้")
    digest = digest.split(":", 1)[1]
    url = asset.get("browser_download_url", "")
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.netloc != "github.com" or
            not parsed.path.startswith("/ultralytics/assets/releases/download/") or
            not parsed.path.endswith("/" + filename) or parsed.query or parsed.fragment):
        raise ValueError("URL โมเดลไม่ได้มาจาก Ultralytics assets")
    size = asset.get("size")
    if type(size) is not int or not 0 < size <= MAX_BYTES:
        raise ValueError("ขนาดโมเดลไม่ถูกต้องหรือเกิน 2 GiB")
    target = registry.path.parent / "downloads" / digest / filename
    check_cancelled()
    cached = target.is_file() and target.stat().st_size == size and file_hash(target) == digest
    if not cached:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="download-", suffix=".part", dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as output, _open(url) as response:
                downloaded = 0
                actual = hashlib.sha256()
                progress(0, size)
                while True:
                    check_cancelled()
                    block = response.read(256 * 1024)
                    if not block:
                        break
                    downloaded += len(block)
                    if downloaded > size:
                        raise ValueError("ไฟล์ดาวน์โหลดมีขนาดเกินข้อมูลที่ประกาศ")
                    actual.update(block)
                    output.write(block)
                    progress(downloaded, size)
                if downloaded != size or actual.hexdigest() != digest:
                    raise ValueError("ตรวจสอบขนาดหรือ SHA-256 โมเดลไม่ผ่าน")
            check_cancelled()
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    check_cancelled()
    row = registry.register(target, preset=preset)
    progress(size, size)
    return dict(kind="download", record=row, version=release.get("tag_name", ""), cached=cached)
