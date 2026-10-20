"""QProcess lifecycle with JSONL framing, cooperative stop and manifest checks."""
import json
from pathlib import Path
import sys
import uuid
from datetime import datetime, timezone
from PySide6.QtCore import QObject, QProcess, Signal
from ..app_paths import data_dir
from ..events import EventParser
from .site_document import atomic_text


class JobController(QObject):
    event = Signal(dict)
    log = Signal(str)
    finished = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self._stdout)
        self.process.readyReadStandardError.connect(self._stderr)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(self._error)
        self.active = False
        self.output = None
        self.log_path = None
        self.session = None
        self.protocol_error = None

    def start(self, output, config=None, demo=False, video_test=None, resume=None):
        if self.active:
            raise ValueError("มีงานกำลังประมวลผลอยู่")
        if sum([bool(config), bool(demo), bool(video_test), bool(resume)]) != 1:
            raise ValueError("เลือกงานเพียงชนิดเดียว: site, demo หรือ video test")
        self.parser = EventParser()
        self.session = str(uuid.uuid4())
        sessions = data_dir()/"sessions"
        sessions.mkdir(exist_ok=True)
        self.control = sessions/f"{self.session}.cancel.json"
        self.log_path = sessions/f"{self.session}.log"
        self.log_path.write_text("", encoding="utf-8")
        self.output = None
        self.protocol_error = None
        self.terminal = None
        self.resumable = not bool(video_test)
        args = ["--output", str(Path(output).resolve()), "--control", str(self.control), "--session", self.session]
        if resume:
            args += ['--resume', str(Path(resume).resolve())]
        elif demo:
            args += ["--demo"]
        else:
            args += ["--video-test" if video_test else "--config", str(Path(video_test or config).resolve())]
        if getattr(sys, "frozen", False):
            program = str(Path(sys.executable).parent/"TBSWorker.exe")
        else:
            program = sys.executable
            args = ["-u", "-m", "tbs.worker", *args]
        self.active = True
        self.process.start(program, args)

    def cancel(self):
        if self.active:
            atomic_text(self.control, json.dumps({"session_id": self.session}))

    def pause(self):
        if self.active and self.resumable:
            atomic_text(self.control, json.dumps(dict(session_id=self.session, action='pause')))

    def force_stop(self):
        if self.active:
            self.protocol_error = "หยุด worker แบบบังคับ; ผลลัพธ์ไม่สมบูรณ์"
            self.process.kill()

    def _append(self, text):
        if self.log_path:
            # A per-session log is bounded at 10 MB; newest diagnostics remain visible.
            if self.log_path.stat().st_size > 10*1024*1024:
                backup = self.log_path.with_suffix(".previous.log")
                self.log_path.replace(backup)
                self.log_path.write_text("", encoding="utf-8")
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(text)
        self.log.emit(text)

    def _stdout(self):
        try:
            for event in self.parser.feed(bytes(self.process.readAllStandardOutput())):
                if event.get("session_id") != self.session:
                    raise ValueError("Worker session mismatch")
                if event["type"] == "started":
                    self.output = event["output"]
                if event["type"] in {"completed", "failed", "cancelled", "paused"}:
                    self.terminal = event
                self.event.emit(event)
        except (ValueError, KeyError, UnicodeError) as exc:
            self.protocol_error = str(exc)
            self._append(f"Protocol error: {exc}\n")
            self.cancel()

    def _stderr(self):
        text = bytes(self.process.readAllStandardError()).decode("utf-8", errors="replace")
        self._append(text)

    def _error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self.active = False
            self.finished.emit("failed", self.process.errorString())

    def _finished(self, code, exit_status):
        self._stdout()
        self._stderr()
        try:
            self.parser.finish()
        except ValueError as exc:
            self.protocol_error = str(exc)
        status = "failed"
        message = self.protocol_error or (self.terminal or {}).get("message", "")
        manifest = None
        manifest_path = Path(self.output)/"manifest.json" if self.output else None
        if manifest_path and manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                message = f"Manifest error: {exc}"
        if not self.protocol_error and exit_status == QProcess.ExitStatus.NormalExit:
            if code == 0 and self.terminal and self.terminal["type"] == "completed" and manifest and manifest.get("status") == "completed":
                status = "completed"
            elif code == 3 and self.terminal and self.terminal["type"] == "cancelled":
                status = "cancelled"
            elif code == 4 and self.terminal and self.terminal['type'] == 'paused' and manifest and manifest.get('status') == 'paused':
                status = 'paused'
        if manifest and manifest.get("status") == "running":
            manifest.update(status="interrupted", error=message or f"Worker exit code {code}",
                            finished_at=datetime.now(timezone.utc).isoformat())
            atomic_text(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False))
        self.active = False
        if self.control.exists():
            self.control.unlink()
        self.finished.emit(status, message or (str(self.output) if status == "completed" else f"Worker exit code {code}"))
