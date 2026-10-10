"""Decode actual presentation timestamps, never frame_index / nominal FPS."""
import av
from .config import timestamp


def frames(config):
    epoch = timestamp(config["epoch"])
    index, previous = 0, None
    for clip_index, clip in enumerate(config["videos"]):
        start = timestamp(clip["start_time"]) - epoch
        first_pts = None
        with av.open(clip["path"]) as container:
            if not container.streams.video:
                raise ValueError(f"No video stream in {clip['path']}")
            stream = container.streams.video[0]
            for frame in container.decode(stream):
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
