import json
from fractions import Fraction
import av
import numpy as np
import pytest
import pyarrow.parquet as pq
import yaml
from tbs.cli import main
from tbs.config import load_site, load_project
from tbs.demo import fixture, benchmark
from tbs.pipeline import run
from tbs.tracking import Tracker
from tbs.trajectory import reconstruct, crossings
from tbs.video import frames


def change(path, edit):
    config = yaml.safe_load(path.read_text())
    edit(config)
    path.write_text(yaml.safe_dump(config))


def test_end_to_end(tmp_path):
    result = benchmark(tmp_path)
    assert result["passed"]
    out = tmp_path/"runs"
    run_dir = next(out.iterdir())
    metadata = pq.read_schema(run_dir/"trajectories.parquet").metadata
    assert metadata[b"schema_version"] == b"1-foundation"
    assert metadata[b"epoch"] == b"2026-01-01T00:00:00Z"
    assert json.loads((run_dir/"manifest.json").read_text())["status"] == "completed"
    assert not (run_dir/"tracks.sqlite").exists()


@pytest.mark.parametrize("edit", [
    lambda c: c.update(schema_version=2),
    lambda c: c["videos"][0].update(path="missing.mkv"),
    lambda c: c["videos"][0].update(start_time="2026-01-01T00:00:00"),
    lambda c: c["road"]["count_lines"][0].update(p2=[13,0]),
    lambda c: c["options"].update(resample_dt=0),
    lambda c: c["road"]["count_lines"].append(c["road"]["count_lines"][0].copy()),
])
def test_invalid_config(tmp_path, edit):
    path = fixture(tmp_path)
    change(path, edit)
    with pytest.raises(ValueError):
        load_site(path)


def test_singular_camera(tmp_path):
    path = fixture(tmp_path)
    (tmp_path/"camera.yaml").write_text(yaml.safe_dump({"projection": "planar_homography", "image_to_ground": [[0,0,0]]*3}))
    with pytest.raises(ValueError, match="invertible"):
        load_site(path)


def test_playlist_pts_and_overlap(tmp_path):
    path = fixture(tmp_path)
    change(path, lambda c: c["videos"].append({"path": "synthetic.mkv", "start_time": "2026-01-01T00:00:10Z"}))
    decoded = list(frames(load_site(path)))
    assert len(decoded) == 100
    assert decoded[50][2:4] == (0.0, 10.0)
    assert decoded[49][3] == pytest.approx(4.9)
    change(path, lambda c: c["videos"][1].update(start_time=c["videos"][0]["start_time"]))
    with pytest.raises(ValueError, match="overlap"):
        list(frames(load_site(path)))


def test_failure_manifest(tmp_path):
    path = fixture(tmp_path/"fixture")
    change(path, lambda c: c["videos"].append(c["videos"][0].copy()))
    with pytest.raises(ValueError, match="overlap"):
        run(path, tmp_path/"runs")
    manifest = next((tmp_path/"runs").glob("*/manifest.json"))
    assert json.loads(manifest.read_text())["status"] == "failed"


def test_empty_detections_have_typed_outputs(tmp_path, monkeypatch):
    path = fixture(tmp_path/"fixture")
    class Empty:
        def detect(self, image):
            return []
    monkeypatch.setattr("tbs.pipeline.make_detector", lambda config: Empty())
    out, report = run(path, tmp_path/"runs")
    assert report["tracks"] == 0
    assert pq.read_table(out/"trajectories.parquet").num_rows == 0


def test_tracker_gap_class_and_one_to_one():
    tracker = Tracker(max_distance=3, max_gap=0.5)
    def det(x, cls=0):
        return {"xy": np.array([x, 0.]), "class_id": cls}
    assert tracker.update(0, [det(0), det(10)]) == [1,2]
    assert tracker.update(0.1, [det(10.2), det(0.2)]) == [2,1]
    assert tracker.update(0.2, [det(0.4, 1)]) == [3]
    assert tracker.update(2, [det(0.6)]) == [4]


def test_no_interpolation_across_gap():
    segments = list(reconstruct([(0,0,0),(.1,1,0),(5,2,0),(5.1,3,0)], max_gap=.5))
    assert len(segments) == 2
    assert all(row["t"] <= .1 or row["t"] >= 5 for segment in segments for row in segment)


def test_finite_line_and_exact_sample():
    line = {"id": "line", "p1": [1,-1], "p2": [1,1]}
    rows = [{"vehicle_id": 1, "t": i, "x": i, "y": 0, "v": 1} for i in range(3)]
    events = list(crossings(rows, [line]))
    assert len(events) == 1
    assert events[0]["t"] == 1
    for row in rows:
        row["y"] = 2
    assert list(crossings(rows, [line])) == []


def test_cli_errors_and_validate(tmp_path, capsys):
    assert main(["validate", str(tmp_path/"absent.yaml")]) == 2
    assert "tbs:" in capsys.readouterr().err
    path = fixture(tmp_path)
    assert main(["validate", str(path)]) == 0


def test_variable_frame_intervals(tmp_path):
    path = fixture(tmp_path)
    with av.open(str(tmp_path/"variable.mkv"), mode="w") as container:
        stream = container.add_stream("ffv1", rate=10)
        stream.width, stream.height, stream.pix_fmt = 32, 32, "bgr0"
        for pts in [0,1,3,7]:
            frame = av.VideoFrame.from_ndarray(np.zeros((32,32,3), dtype=np.uint8), format="bgr24")
            frame.pts, frame.time_base = pts, Fraction(1,10)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    change(path, lambda c: c["videos"][0].update(path="variable.mkv"))
    assert [row[3] for row in frames(load_site(path))] == pytest.approx([0,.1,.3,.7])


def test_project_references_and_epoch(tmp_path):
    site = fixture(tmp_path)
    project = tmp_path/"project.yaml"
    config = {"schema_version": 1, "project_id": "test", "epoch": "2026-01-01T00:00:00Z",
              "sites": [{"id": "synthetic", "config": site.name}], "links": []}
    project.write_text(yaml.safe_dump(config))
    assert load_project(project)["sites"][0]["id"] == "synthetic"
    change(project, lambda c: c["links"].append({"from": "synthetic", "to": "missing", "distance_m": 100}))
    with pytest.raises(ValueError, match="unknown"):
        load_project(project)
    change(project, lambda c: c.update(links=[], epoch="2026-01-02T00:00:00Z"))
    with pytest.raises(ValueError, match="epoch"):
        load_project(project)


def test_resample_guard():
    with pytest.raises(ValueError, match="limit"):
        list(reconstruct([(0,0,0),(1,1,0)], dt=1e-8, max_gap=2))
