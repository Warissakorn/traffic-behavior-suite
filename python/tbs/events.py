"""Versioned worker events and a bounded incremental UTF-8 JSONL decoder."""
import json


class CancelledError(Exception):
    """A cooperative user cancellation, not a processing error."""


class EventParser:
    def __init__(self, limit=1024*1024):
        self.buffer = b""
        self.limit = limit

    def feed(self, chunk):
        self.buffer += bytes(chunk)
        events = []
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            if len(line) > self.limit:
                raise ValueError("Worker event exceeds size limit")
            if not line.strip():
                continue
            event = json.loads(line.decode("utf-8"))
            if not isinstance(event, dict) or event.get("event_version") != 1:
                raise ValueError("Unsupported worker event protocol")
            if event.get("type") not in {"started", "stage", "progress", "warning", "heartbeat", "completed", "cancelled", "failed"}:
                raise ValueError("Unknown worker event type")
            events.append(event)
        if len(self.buffer) > self.limit:
            raise ValueError("Worker event exceeds size limit")
        return events

    def finish(self):
        if self.buffer.strip():
            raise ValueError("Incomplete worker event")
