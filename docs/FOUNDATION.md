# Foundation and single-site Python reference

This increment is executable infrastructure, not completion of Roadmap phases 0–2.
Real-site ground truth and baselines from the predecessor applications are still required.

## Quick start

```bash
python -m pip install -e ".[dev]"
tbs demo --output demo-output
tbs validate demo-output/fixture/site.yaml
tbs run demo-output/fixture/site.yaml --output output
python -m pytest -q
```

The demo generates a lossless 50-frame video of a moving green rectangle, a camera
mapping, and a site YAML. Its benchmark checks a known 4 m/s speed, position and
one line crossing at 2.5 s. It does not measure accuracy on real traffic.

## Real video

Install `python -m pip install -e ".[detect]"` and use **local** YOLO weights (`.pt`
or an Ultralytics-compatible exported model). The package does not download weights.
Use the generated site YAML or `configs/foundation.site.example.yaml` as the
currently supported config example (replace all placeholder paths/calibration):

* `videos[].start_time` is required and timezone-aware. It refers to the first
  decoded frame of each clip. Relative paths resolve from the site YAML directory.
* `epoch` defaults to the first clip's start time. `frames.parquet` preserves each
  clip's relative decoded PTS (`t_video`), clip index and run-relative time (`t`).
  Overlapping/non-monotonic timestamps fail explicitly; no nominal FPS timestamps.
* Camera YAML requires `projection: planar_homography` and a finite invertible
  `image_to_ground` matrix mapping **already undistorted image pixels to metres**.
  Full K/dist/R/t calibration and uncertainty estimation remain future work.
* The detector projects the bottom centre of each box. Ground-plane nearest
  association uses Hungarian assignment, class gating and constant velocity.
* Set `options.class_ids` to the actual traffic class IDs of your model. IDs are
  preserved, not automatically mapped to the Thai vehicle taxonomy.
* `road.count_lines` uses ground coordinates. Direction is positive when the
  trajectory crosses from the negative to positive side of oriented p1→p2.
* Tracking tolerances are `track_max_distance_m` (default 3) and
  `track_max_gap_s` (default 0.5). Tune them against labelled footage.

## Outputs and failure handling

Each run writes `<output>/<uuid>/manifest.json`, resolved configuration, and typed
Parquet files: frames, detections, trajectories, vehicles, line_crossings and runs.
Metadata contains site/run IDs, epoch, config hash and engine version. The manifest
also records model hashes, counters, warnings and completion/failure state.
Only consume outputs when the manifest reports `status: completed`.

`schema_version=1-foundation` marks an **explicit subset** of the draft v1 schema.
Unimplemented lane/headway/quality fields are null or use the documented -1 sentinel;
clock offset/drift are null. No quality probabilities are fabricated. Detections
omit keypoints/covariance and vehicles omit dimensions/OD/colour. Full schema v1
compatibility will be introduced with the stages that can compute these fields.

Decode/inference and detection writes stream in batches of 128 frames. Raw track
samples spool to SQLite, then reconstruction loads one vehicle at a time (limit
100,000 samples). Resampling uses interpolation and Savitzky–Golay smoothing,
splitting gaps above `max_interpolation_gap_s`; it is **not an RTS smoother**.
Short tracks may have no reconstructed rows. No 24-hour bounded-memory guarantee
or resume capability is claimed. Successful runs remove the temporary SQLite file.
Failures retain diagnostics and mark partial results as failed.

The older `configs/site.example.yaml` describes the future full SPEC and is not
accepted by this narrower runtime. The installed validation schema is bundled at
`python/tbs/schemas/site.json` so validation also works from a wheel.

## Remaining Foundation gates

1. Obtain approved labelled footage from ≥2 sites and field control points/probe GPS.
2. Import CVAT annotations and record predecessor-app count/tracking baselines.
3. Add real-video detection/tracking/position/speed metrics and hold-out site splits.
4. Add full camera calibration, RTS smoothing, lane/Frenet and overlay review.
5. Add project config and cross-site identity/time contracts before Re-ID.

CI exercises the synthetic regression on Windows/Linux and Python 3.10/3.12.
The YOLO adapter still requires a smoke test with the team's actual local weights.

`tbs validate configs/project.example.yaml --kind project` validates the project,
each referenced site, a common epoch and link references. Project execution and
cross-site matching remain future work.
