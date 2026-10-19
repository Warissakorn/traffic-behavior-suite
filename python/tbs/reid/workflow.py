"""Import completed site runs, build reviewable matches, and export observed OD."""
from collections import Counter
from datetime import datetime, timezone
import csv
import hashlib
import heapq
import json
import math
from pathlib import Path
import uuid

import cv2
import numpy as np
import pyarrow.parquet as pq
import yaml

from .. import __version__
from ..config import timestamp
from ..events import CancelledError
from ..video import VideoReader
from .features import Appearance, normalized
from .solver import match, review, journeys


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def _number(value, name):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    return value


def validate_config(config, base=None):
    base = Path(base or Path.cwd())
    config = json.loads(json.dumps(config, allow_nan=False))
    if not isinstance(config, dict) or config.get('schema_version') != 1:
        raise ValueError('Expected OD config schema_version: 1')
    if set(config) - {'schema_version', 'observations', 'links', 'options'}:
        raise ValueError('Unknown OD configuration field')
    observations, links = config.get('observations'), config.get('links')
    if not isinstance(observations, list) or not 2 <= len(observations) <= 100:
        raise ValueError('Add 2–100 observations with completed site runs')
    ids, points, runs, offsets = set(), set(), set(), {}
    for observation in observations:
        if not isinstance(observation, dict) or set(observation) - {'id', 'point_id', 'run', 'clock_offset_s', 'passage_point'}:
            raise ValueError('Unknown or invalid observation field')
        for key in ['id', 'point_id', 'run']:
            if not isinstance(observation.get(key), str) or not observation[key].strip():
                raise ValueError(f'Observation requires {key}')
        if observation['id'] in ids:
            raise ValueError('Observation IDs must be unique')
        ids.add(observation['id'])
        points.add(observation['point_id'])
        observation['run'] = str((base / observation['run']).resolve())
        selector = observation.get('passage_point')
        if selector is not None and (not isinstance(selector, str) or not selector.strip()):
            raise ValueError('passage_point must be a nonempty point gate ID')
        selection = (observation['run'], selector)
        if selection in runs or (any(path == observation['run'] for path, _ in runs) and
                                 (selector is None or (observation['run'], None) in runs)):
            raise ValueError('The same run requires distinct passage_point selections; whole-run duplicates are not allowed')
        runs.add(selection)
        _number(observation.setdefault('clock_offset_s', 0), 'clock_offset_s')
        if observation['run'] in offsets and offsets[observation['run']] != observation['clock_offset_s']:
            raise ValueError('Observations from the same run must have the same clock offset')
        offsets[observation['run']] = observation['clock_offset_s']
    if not isinstance(links, list) or not links:
        raise ValueError('Add at least one directed link and travel-time window')
    edges = set()
    for link in links:
        if not isinstance(link, dict) or set(link) - {'from', 'to', 'min_travel_s', 'max_travel_s'}:
            raise ValueError('Unknown or invalid link field')
        edge = (link.get('from'), link.get('to'))
        if edge[0] not in points or edge[1] not in points or edge in edges:
            raise ValueError('Unknown or duplicate point link')
        edges.add(edge)
        low = _number(link.get('min_travel_s'), 'min_travel_s')
        high = _number(link.get('max_travel_s'), 'max_travel_s')
        if not 0 < low <= high:
            raise ValueError('Travel window requires 0 < minimum <= maximum')
    options = config.setdefault('options', {})
    if not isinstance(options, dict):
        raise ValueError('OD options must be an object')
    if set(options) - {'min_similarity', 'ambiguity_margin', 'input_size', 'reid_model', 'identity_mode', 'reid_device'}:
        raise ValueError('Unknown OD option')
    if options.setdefault('identity_mode', 'independent') not in {'independent', 'shared_track'}:
        raise ValueError('identity_mode must be independent or shared_track')
    device = options.setdefault('reid_device', 'cpu')
    if not isinstance(device, str) or (device not in {'cpu', 'auto'} and not device.removeprefix('cuda:').isdecimal()):
        raise ValueError('reid_device must be cpu, auto or a CUDA device index')
    threshold = _number(options.setdefault('min_similarity', .85), 'min_similarity')
    margin = _number(options.setdefault('ambiguity_margin', .05), 'ambiguity_margin')
    if not 0 < threshold < 1 or not 0 <= margin <= 1:
        raise ValueError('Similarity must be between 0 and 1; ambiguity margin between 0 and 1')
    size = options.setdefault('input_size', [128, 256])
    if not isinstance(size, list) or len(size) != 2 or any(type(v) is not int or not 16 <= v <= 2048 for v in size):
        raise ValueError('ONNX input_size must be [width, height], each 16–2048')
    if options.get('reid_model'):
        options['reid_model'] = str((base / options['reid_model']).resolve())
    return config


def load_config(path):
    path = Path(path).resolve()
    return validate_config(yaml.safe_load(path.read_text(encoding='utf-8')), path.parent)


def _batches(run, name, run_id, columns=None):
    with pq.ParquetFile(run / f'{name}.parquet') as file:
        metadata = file.schema_arrow.metadata or {}
        if metadata.get(b'run_id', b'').decode() != run_id:
            raise ValueError(f'Run metadata mismatch: {name}')
        for batch in file.iter_batches(batch_size=1024, columns=columns):
            yield batch.to_pylist()


def extract_sightings(observation, appearance, output, check_cancel, progress):
    run = Path(observation['run'])
    manifest = json.loads((run / 'manifest.json').read_text(encoding='utf-8'))
    if (manifest.get('schema_version') != '1-foundation' or manifest.get('status') != 'completed'
            or manifest.get('run_mode', 'site') != 'site'):
        raise ValueError('Import completed site analysis with track IDs, not detection-only or partial runs')
    run_id = manifest['run_id']
    config = json.loads((run / 'config.resolved.json').read_text(encoding='utf-8'))
    if config['site_id'] != manifest['site_id'] or config['epoch'] != manifest['epoch']:
        raise ValueError('Site config and manifest do not agree')
    epoch = timestamp(config['epoch']) + observation['clock_offset_s']
    vehicles = {}
    for rows in _batches(run, 'vehicles', run_id):
        check_cancel()
        for vehicle in rows:
            if vehicle['vehicle_id'] in vehicles:
                raise ValueError('Duplicate local vehicle ID')
            vehicles[vehicle['vehicle_id']] = vehicle
            if len(vehicles) > 5000:
                raise ValueError('More than 5000 vehicles in one observation; split the survey')
    instances = {}
    gate = observation.get('passage_point')
    if gate is not None:
        if gate not in {p['id'] for p in config.get('image_regions', {}).get('points', [])}:
            raise ValueError(f'Unknown source passage_point: {gate}; rerun the site with this point gate')
        for rows in _batches(run, 'point_passages', run_id):
            check_cancel()
            for passage in rows:
                if passage['point_id'] != gate:
                    continue
                vehicle = vehicles.get(passage['vehicle_id'])
                if vehicle is None:
                    raise ValueError('Point passage references an unknown vehicle')
                key = f"{vehicle['vehicle_id']}:{passage['passage_id']}"
                if key in instances:
                    raise ValueError('Duplicate point passage')
                instances[key] = dict(vehicle, t_first=passage['t'], t_last=passage['t'],
                                      passage_id=passage['passage_id'])
                if len(instances) > 10000:
                    raise ValueError('More than 10000 point passages; split the survey')
    else:
        instances = dict(vehicles)
    by_vehicle = {}
    for key, instance in instances.items():
        by_vehicle.setdefault(instance['vehicle_id'], []).append(key)
    best = {key: [] for key in instances}
    for rows in _batches(run, 'detections', run_id):
        check_cancel()
        for det in rows:
            key = det['track_id']
            if key not in vehicles:
                raise ValueError('Detection references an unknown vehicle')
            values = [det[name] for name in ['x1', 'y1', 'x2', 'y2', 'score']]
            if not all(value is not None and math.isfinite(value) for value in values):
                raise ValueError('Nonfinite detection coordinates or confidence')
            quality = max(0, det['x2'] - det['x1']) * max(0, det['y2'] - det['y1']) * max(0, det['score'])
            if quality <= 0:
                continue
            for instance_key in by_vehicle.get(key, []):
                sample_quality = quality
                if gate is not None:
                    distance = abs(det['t']-instances[instance_key]['t_first'])
                    if distance > max(1, 2*config.get('options', {}).get('track_max_gap_s', .5)):
                        continue
                    sample_quality /= 1 + 100*distance
                entry = (sample_quality, det['det_id'], det)
                if len(best[instance_key]) < 3:
                    heapq.heappush(best[instance_key], entry)
                elif entry[:2] > best[instance_key][0][:2]:
                    heapq.heapreplace(best[instance_key], entry)
    needed = {item[2]['frame_index'] for selected in best.values() for item in selected}
    frames = {}
    for rows in _batches(run, 'frames', run_id):
        check_cancel()
        frames.update({r['frame_index']: r for r in rows if r['frame_index'] in needed})
    reader = VideoReader()
    sightings = []
    try:
        for key, vehicle in instances.items():
            check_cancel()
            entry_time, exit_time = epoch + vehicle['t_first'], epoch + vehicle['t_last']
            if not math.isfinite(entry_time) or not math.isfinite(exit_time) or entry_time > exit_time:
                raise ValueError('Invalid track timestamps')
            identity = hashlib.sha256(f"{observation['id']}:{run_id}:{key}".encode()).hexdigest()[:24]
            vectors, weights, crop_paths = [], [], []
            for sample_index, (weight, _, det) in enumerate(sorted(best[key], key=lambda item: item[:2], reverse=True)):
                check_cancel()
                frame = frames.get(det['frame_index'])
                if frame is None:
                    raise ValueError('Missing representative frame')
                clip = config['videos'][frame['clip_index']]
                decoded = reader.read(clip['path'], frame['t_video'])
                if abs(decoded['t_video'] - frame['t_video']) > .001:
                    raise ValueError('Representative frame timestamp differs from source video')
                bgr = cv2.cvtColor(decoded['image'], cv2.COLOR_RGB2BGR)
                height, width = bgr.shape[:2]
                x1, y1 = max(0, math.floor(det['x1'])), max(0, math.floor(det['y1']))
                x2, y2 = min(width, math.ceil(det['x2'])), min(height, math.ceil(det['y2']))
                crop = bgr[y1:y2, x1:x2]
                if crop.size == 0:
                    continue
                vectors.append(appearance.extract(crop))
                weights.append(weight)
                crop_path = f'crops/{identity}-{sample_index}.jpg'
                preview = crop
                if max(crop.shape[:2]) > 512:
                    scale = 512 / max(crop.shape[:2])
                    preview = cv2.resize(crop, (max(1, int(crop.shape[1]*scale)), max(1, int(crop.shape[0]*scale))))
                ok, encoded = cv2.imencode('.jpg', preview)
                if not ok:
                    raise ValueError('Cannot encode vehicle preview')
                (output / crop_path).write_bytes(encoded.tobytes())
                crop_paths.append(dict(path=crop_path, time=epoch + det['t'], frame_index=det['frame_index']))
            if not vectors:
                raise ValueError(f'No usable appearance crops for vehicle {key}')
            embedding = normalized(np.average(vectors, axis=0, weights=weights)).tolist()
            sightings.append(dict(id=identity, observation_id=observation['id'], point_id=observation['point_id'],
                                  run_id=run_id, local_vehicle_id=vehicle['vehicle_id'], class_id=vehicle['class_id'],
                                  passage_point=gate, source_passage_id=vehicle.get('passage_id'),
                                  entry_time=entry_time, exit_time=exit_time, crop=crop_paths[0]['path'], crops=crop_paths,
                                  samples=len(vectors), embedding=embedding))
            progress(f"{observation['id']}: {len(sightings)}/{len(instances)} sightings")
    finally:
        reader.close()
    return sightings, run_id


def run(config, output_dir, *, should_cancel=lambda: False, on_progress=lambda message: None):
    config = validate_config(config)
    def check_cancel():
        if should_cancel():
            raise CancelledError('Cancelled cross-camera matching')
    check_cancel()
    output = Path(output_dir).resolve() / str(uuid.uuid4())
    (output / 'crops').mkdir(parents=True)
    manifest = dict(schema_version='1-reid', status='running', engine_version=__version__,
                    created_at=datetime.now(timezone.utc).isoformat(), config=config)
    atomic_json(output / 'manifest.json', manifest)
    try:
        appearance = Appearance(config['options'])
        sightings, run_ids = [], {}
        for observation in config['observations']:
            check_cancel()
            on_progress(f"Reading {observation['id']}")
            rows, run_id = extract_sightings(observation, appearance, output, check_cancel, on_progress)
            if run_id in run_ids and run_ids[run_id] != observation['run']:
                raise ValueError('Duplicate source run ID, possibly copied results')
            run_ids[run_id] = observation['run']
            sightings.extend(rows)
            if len(sightings) > 10000:
                raise ValueError('More than 10000 sightings; split the survey')
        on_progress('Matching appearance and travel-time candidates')
        pairs = match(sightings, config['links'], config['options']['min_similarity'],
                      config['options']['ambiguity_margin'], check_cancel,
                      identity_mode=config['options']['identity_mode'])
        check_cancel()
        result = dict(schema_version='1-reid', config=config, appearance=appearance.metadata,
                      sightings=sightings, candidates=pairs, journeys=[], source_reviews={},
                      warning='All proposed identities require review. OD covers observed points, not actual trip endpoints.')
        atomic_json(output / 'result.json', result)
        manifest.update(status='completed', sightings=len(sightings), candidate_pairs=len(pairs),
                        appearance=appearance.metadata, finished_at=datetime.now(timezone.utc).isoformat())
        atomic_json(output / 'manifest.json', manifest)
        return str(output), result
    except BaseException as exc:
        manifest.update(status='cancelled' if isinstance(exc, CancelledError) else 'failed',
                        error=f'{type(exc).__name__}: {exc}')
        atomic_json(output / 'manifest.json', manifest)
        raise


def load_result(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != '1-reid' or manifest.get('status') != 'completed':
        raise ValueError('Expected a completed cross-camera matching result')
    result = json.loads((directory / 'result.json').read_text(encoding='utf-8'))
    if result.get('schema_version') != '1-reid':
        raise ValueError('Unsupported matching result')
    from .solver import validate_sightings
    validate_sightings(result['sightings'])
    config = validate_config(result['config'])
    if config != validate_config(manifest.get('config')):
        raise ValueError('Matching result and manifest configuration differ')
    lookup = {s['id']: s for s in result['sightings']}
    pair_ids, edges = set(), set()
    links = {(link['from'], link['to']): link for link in config['links']}
    for pair in result['candidates']:
        edge = (pair.get('source'), pair.get('target'))
        if (not isinstance(pair.get('id'), str) or not pair['id'] or pair['id'] in pair_ids
                or edge in edges or edge[0] not in lookup or edge[1] not in lookup):
            raise ValueError('Invalid or duplicate candidate identity')
        pair_ids.add(pair['id'])
        edges.add(edge)
        a, b = lookup[edge[0]], lookup[edge[1]]
        link = links.get((a['point_id'], b['point_id']))
        travel = b['entry_time'] - a['exit_time']
        if (link is None or not link['min_travel_s'] <= travel <= link['max_travel_s']
                or a['class_id'] != b['class_id'] or a['observation_id'] == b['observation_id']):
            raise ValueError('Candidate does not satisfy route, time or class constraints')
        if (config['options']['identity_mode'] == 'shared_track' and a.get('run_id') == b.get('run_id')
                and a.get('local_vehicle_id') != b.get('local_vehicle_id')):
            raise ValueError('Same-run point candidates must use the same vehicle track')
        if (pair.get('status') not in {'pending', 'accepted', 'rejected'}
                or type(pair.get('suggested')) is not bool or type(pair.get('ambiguous')) is not bool):
            raise ValueError('Invalid candidate review status')
        similarity = _number(pair.get('similarity'), 'similarity')
        travel_s = _number(pair.get('travel_s'), 'travel_s')
        if not -1 <= similarity <= 1 or abs(travel_s - travel) > 1e-6:
            raise ValueError('Invalid candidate score or travel time')
    result['journeys'] = journeys(result['sightings'], result['candidates'])
    for sighting in result['sightings']:
        paths = [sighting['crop']] + [c['path'] for c in sighting.get('crops', [])]
        for path in paths:
            if not (directory / path).resolve().is_relative_to(directory):
                raise ValueError('Crop path is outside the result directory')
    return result


def save_review(directory, result, pair_id, decision):
    # Do not leave the in-memory review changed if persistence fails.
    updated = json.loads(json.dumps(result))
    review(updated, pair_id, decision)
    pair = next(c for c in updated['candidates'] if c['id'] == pair_id)
    pair['reviewed_at'] = datetime.now(timezone.utc).isoformat() if decision != 'pending' else None
    atomic_json(Path(directory) / 'result.json', updated)
    return updated


def save_no_match(directory, result, source_id):
    if source_id not in {s['id'] for s in result['sightings']}:
        raise ValueError('Unknown source sighting')
    if any(c['source'] == source_id and c['status'] == 'accepted' for c in result['candidates']):
        raise ValueError('ถอนคู่ที่ยืนยันแล้วก่อนเลือกไม่พบคู่')
    updated = json.loads(json.dumps(result))
    when = datetime.now(timezone.utc).isoformat()
    for candidate in updated['candidates']:
        if candidate['source'] == source_id:
            candidate.update(status='rejected', reviewed_at=when)
    updated.setdefault('source_reviews', {})[source_id] = dict(decision='no_match', reviewed_at=when)
    updated['journeys'] = journeys(updated['sightings'], updated['candidates'])
    atomic_json(Path(directory) / 'result.json', updated)
    return updated


def clear_no_match(directory, result, source_id):
    if source_id not in {s['id'] for s in result['sightings']}:
        raise ValueError('Unknown source sighting')
    updated = json.loads(json.dumps(result))
    updated.get('source_reviews', {}).pop(source_id, None)
    atomic_json(Path(directory) / 'result.json', updated)
    return updated


def export_csv(result, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    names = ['sightings', 'pairs', 'journeys', 'od']
    if any((directory / f'{name}.csv').exists() for name in names):
        raise ValueError('Export destination already contains OD files; select a new directory')
    reviewed = journeys(result['sightings'], result['candidates'])
    counts = Counter((r['origin'], r['destination'], r['class_id']) for r in reviewed)
    tables = {
        'sightings': (['id', 'observation_id', 'point_id', 'run_id', 'local_vehicle_id', 'passage_point', 'source_passage_id', 'class_id', 'entry_time', 'exit_time', 'crop', 'successor_review'],
                      [dict(s, successor_review=result.get('source_reviews', {}).get(s['id'], {}).get('decision', '')) for s in result['sightings']]),
        'pairs': (['id', 'source', 'target', 'rank', 'similarity', 'travel_s', 'identity_method', 'suggested', 'ambiguous', 'status', 'reviewed_at'], result['candidates']),
        'journeys': (['journey_id', 'origin', 'destination', 'class_id', 'departure_time', 'arrival_time', 'travel_s', 'points', 'sightings', 'status'], reviewed),
        'od': (['origin', 'destination', 'class_id', 'vehicles'], [dict(origin=k[0], destination=k[1], class_id=k[2], vehicles=v) for k, v in sorted(counts.items())])}
    for name, (fields, rows) in tables.items():
        temporary = directory / f'{name}.csv.tmp'
        with temporary.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            for row in rows:
                values = {key: row.get(key) for key in fields}
                for key, value in values.items():
                    if isinstance(value, list):
                        values[key] = json.dumps(value, ensure_ascii=False)
                    elif key in {'entry_time', 'exit_time', 'departure_time', 'arrival_time'}:
                        values[key] = datetime.fromtimestamp(value, timezone.utc).isoformat()
                writer.writerow(values)
        temporary.replace(directory / f'{name}.csv')
    atomic_json(directory / 'provenance.json', dict(schema_version='1-reid', appearance=result['appearance'],
                                                  config=result['config'], warning=result['warning']))
