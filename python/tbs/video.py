"""Decode actual presentation timestamps, never frame_index / nominal FPS."""
import av
import math
from pathlib import Path
from .config import timestamp
from .camera_calibration import check_image_size


def frame_time(frame):
    if frame.pts is None or frame.time_base is None:
        raise ValueError("วิดีโอไม่มี timestamp (PTS) ที่อ่านได้")
    return float(frame.pts * frame.time_base)


class VideoReader:
    """One bounded decoder, reused for playback; callers serialize read/close.

    Keep only the frames surrounding the requested PTS. Forward playback decodes
    sequentially; scrubbing seeks to a keyframe and then decodes to the target.
    """

    def __init__(self):
        self.container = None
        self.path = None

    def close(self):
        if self.container is not None:
            self.container.close()
        self.container = self.path = None
        self.current = self.previous = self.decoder = None

    def _timing(self):
        """Probe the final GOP, bounded to 512 frames, then rewind.

        Container duration may include a nonzero PTS origin (notably Matroska),
        so do not treat it as a relative clip duration. It is only a seek hint.
        """
        duration = last_time = None
        hint = self.container.duration
        if hint is None and self.stream.duration is not None and self.stream.time_base is not None:
            hint = int(float(self.stream.duration*self.stream.time_base)*av.time_base)
        if hint is not None and self.stream.time_base is not None:
            try:
                end = self.first_pts + abs(float(hint/av.time_base)) + 1
                self.container.seek(int(end/float(self.stream.time_base)), stream=self.stream, backward=True)
                last = None
                tail = iter(self.container.decode(self.stream))
                for _ in range(512):
                    frame = next(tail, None)
                    if frame is None:
                        if last is not None:
                            last_time = frame_time(last)-self.first_pts
                            frame_duration = float((getattr(last, "duration", 0) or 0)*last.time_base)
                            duration = last_time + max(0, frame_duration)
                        break
                    last = frame
            except (av.FFmpegError, ValueError, OverflowError):
                pass
            try:
                self.container.seek(int(self.first_pts/float(self.stream.time_base)), stream=self.stream, backward=True)
                self.decoder = iter(self.container.decode(self.stream))
                self.current = next(self.decoder, None)
                if self.current is None:
                    raise ValueError("Cannot rewind video")
            except (av.FFmpegError, ValueError):
                path = self.container.name
                self.container.close()
                self.container = av.open(path)
                self.stream = self.container.streams.video[0]
                self.decoder = iter(self.container.decode(self.stream))
                self.current = next(self.decoder, None)
        return duration if duration is not None and duration > 0 else None, last_time

    def _open(self, path):
        self.close()
        path = str(Path(path).resolve())
        if not Path(path).is_file():
            raise ValueError(f"ไม่พบวิดีโอ: {path}")
        try:
            self.container = av.open(path)
            if not self.container.streams.video:
                raise ValueError("ไฟล์นี้ไม่มี video stream")
            self.stream = self.container.streams.video[0]
            self.decoder = iter(self.container.decode(self.stream))
            self.current = next(self.decoder, None)
            if self.current is None:
                raise ValueError("ไม่มีเฟรมวิดีโอที่อ่านได้")
            self.first_pts = frame_time(self.current)
            duration, last_time = self._timing()
            self.info = dict(width=self.current.width, height=self.current.height,
                             duration_s=duration, last_time_s=last_time)
            self.previous = None
            self.eof = False
            self.last_target = 0.0
            self.path = path
        except BaseException:
            self.close()
            raise

    def read(self, path, t_video=0.0):
        path = str(Path(path).resolve())
        target = float(t_video)
        if not math.isfinite(target) or target < 0:
            raise ValueError("เวลาในวิดีโอต้องเป็นจำนวนที่ไม่ติดลบ")
        if path != self.path:
            self._open(path)
        earliest = frame_time(self.previous or self.current) - self.first_pts
        if target < earliest - 1e-9 or target - self.last_target > 1:
            self.container.seek(int((self.first_pts + target) / float(self.stream.time_base)),
                                stream=self.stream, backward=True)
            self.decoder = iter(self.container.decode(self.stream))
            self.previous = None
            self.current = next(self.decoder, None)
            if self.current is None:
                raise ValueError("ไม่สามารถเลื่อนไปยังเวลานี้ได้")
            self.eof = False
        while frame_time(self.current) - self.first_pts < target and not self.eof:
            following = next(self.decoder, None)
            if following is None:
                self.eof = True
                break
            if frame_time(following) <= frame_time(self.current):
                raise ValueError("PTS ของวิดีโอไม่เพิ่มขึ้นตามลำดับ")
            self.previous, self.current = self.current, following
        best = self.current
        if self.previous is not None:
            if abs(frame_time(self.previous) - self.first_pts - target) <= abs(frame_time(best) - self.first_pts - target):
                best = self.previous
        self.last_target = target
        return dict(image=best.to_ndarray(format="rgb24"),
                    t_video=frame_time(best) - self.first_pts, eof=self.eof, info=self.info)


def probe_video(path):
    reader = VideoReader()
    try:
        reader.read(path)
        return dict(reader.info)
    finally:
        reader.close()


def check_playlist(config):
    """Fast GUI preflight; the decoder remains the authority for exact PTS."""
    clips = config["videos"]
    starts = [timestamp(clip["start_time"]) for clip in clips]
    infos = [probe_video(clip["path"]) for clip in clips]
    for info in infos:
        check_image_size(config.get('camera', {}), [info['width'], info['height']])
    for index in range(1, len(clips)):
        last_time = infos[index - 1]["last_time_s"]
        if starts[index] <= starts[index - 1] or (last_time is not None and
                starts[index] <= starts[index - 1] + last_time + 1e-6):
            raise ValueError(f"เวลาเริ่มวิดีโอรายการ {index + 1} ซ้อนกับรายการก่อนหน้า")
    return infos


def frames(config, start_clip=0, stop_clip=None, start_index=0, previous=None):
    epoch = timestamp(config["epoch"])
    index = start_index
    for clip_index in range(start_clip, len(config['videos']) if stop_clip is None else stop_clip):
        clip = config['videos'][clip_index]
        start = timestamp(clip["start_time"]) - epoch
        first_pts = None
        with av.open(clip["path"]) as container:
            if not container.streams.video:
                raise ValueError(f"No video stream in {clip['path']}")
            stream = container.streams.video[0]
            for frame in container.decode(stream):
                check_image_size(config.get('camera', {}), [frame.width, frame.height])
                if frame.pts is None or frame.time_base is None:
                    raise ValueError(f"Missing PTS in {clip['path']}")
                pts = float(frame.pts * frame.time_base)
                if first_pts is None:
                    first_pts = pts
                t_video = pts - first_pts
                t = start + t_video
                if previous is not None and t <= previous:
                    raise ValueError("Playlist timestamps overlap or are not strictly increasing")
                yield index, clip_index, t_video, t, frame.to_ndarray(format="bgr24")
                previous, index = t, index + 1
