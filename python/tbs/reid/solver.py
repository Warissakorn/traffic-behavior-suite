"""Time-gated, optional one-to-one matching; all identities need human review."""
from bisect import bisect_left, bisect_right
from collections import defaultdict
import hashlib
import math
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import min_weight_full_bipartite_matching


def validate_sightings(sightings):
    ids = set()
    dimension = None
    for row in sightings:
        if row['id'] in ids:
            raise ValueError('Duplicate sighting ID')
        ids.add(row['id'])
        vector = np.asarray(row['embedding'], dtype=float)
        if (vector.ndim != 1 or not vector.size or not np.isfinite(vector).all()
                or abs(np.linalg.norm(vector) - 1) > 1e-5):
            raise ValueError('Sightings require normalized finite embeddings')
        if dimension is not None and dimension != vector.size:
            raise ValueError('Embedding dimensions differ')
        dimension = vector.size
        if not all(math.isfinite(row[key]) for key in ['entry_time', 'exit_time']):
            raise ValueError('Sighting times must be finite')
        if row['exit_time'] < row['entry_time']:
            raise ValueError('Sighting exit precedes entry')


def match(sightings, links, min_similarity=.85, ambiguity_margin=.05, check_cancel=lambda: None,
          identity_mode='independent'):
    validate_sightings(sightings)
    if not 0 < min_similarity < 1 or not 0 <= ambiguity_margin <= 1:
        raise ValueError('Invalid similarity threshold or ambiguity margin')
    if identity_mode not in {'independent', 'shared_track'}:
        raise ValueError('Unknown identity mode')
    points = defaultdict(list)
    for index, row in enumerate(sightings):
        points[row['point_id']].append(index)
    for indices in points.values():
        indices.sort(key=lambda index: sightings[index]['entry_time'])
    candidates = []
    examined = 0
    for link in links:
        targets = points[link['to']]
        times = [sightings[i]['entry_time'] for i in targets]
        for i in points[link['from']]:
            check_cancel()
            left = bisect_left(times, sightings[i]['exit_time'] + link['min_travel_s'])
            right = bisect_right(times, sightings[i]['exit_time'] + link['max_travel_s'])
            for j in targets[left:right]:
                examined += 1
                if examined > 200000:
                    raise ValueError('More than 200000 candidate comparisons; narrow time windows or split the survey')
                a, b = sightings[i], sightings[j]
                # Local IDs label observations; independent matching does not
                # assume identity continuity between observation points.
                if a['observation_id'] == b['observation_id'] or a['class_id'] != b['class_id']:
                    continue
                same_run = (identity_mode == 'shared_track' and bool(a.get('run_id'))
                            and a.get('run_id') == b.get('run_id'))
                if same_run and a['local_vehicle_id'] != b['local_vehicle_id']:
                    continue
                similarity = float(np.clip(np.dot(a['embedding'], b['embedding']), -1, 1))
                if not same_run and similarity <= min_similarity:
                    continue
                key = hashlib.sha256((a['id'] + ':' + b['id']).encode()).hexdigest()[:20]
                candidates.append(dict(id=key, source=a['id'], target=b['id'], similarity=similarity,
                                       travel_s=b['entry_time'] - a['exit_time'],
                                       identity_method='shared_track' if same_run else 'appearance',
                                       suggested=False, ambiguous=False, status='pending', _i=i, _j=j))
    if candidates:
        n = len(sightings)
        # Every source has its own unmatched dummy column. Costs above zero keep
        # the sparse representation valid even for identical descriptors.
        rows = [c['_i'] for c in candidates] + list(range(n))
        cols = [c['_j'] for c in candidates] + list(range(n, 2*n))
        def score(c):
            return 1.0 if c['identity_method'] == 'shared_track' else c['similarity']
        costs = [1 - score(c) + 1e-9 for c in candidates] + [1 - min_similarity + 1e-9] * n
        graph = csr_matrix((costs, (rows, cols)), shape=(n, 2*n))
        check_cancel()
        assigned_rows, assigned_cols = min_weight_full_bipartite_matching(graph)
        chosen = set(zip(assigned_rows, assigned_cols))
        outgoing, incoming = defaultdict(list), defaultdict(list)
        for c in candidates:
            outgoing[c['source']].append(c)
            incoming[c['target']].append(c)
        for c in candidates:
            c['suggested'] = (c['_i'], c['_j']) in chosen
            alternatives = [score(other) for other in outgoing[c['source']] + incoming[c['target']]
                            if other['id'] != c['id']]
            c['ambiguous'] = bool(alternatives and score(c) - max(alternatives) < ambiguity_margin)
    for c in candidates:
        del c['_i'], c['_j']
    by_source = defaultdict(list)
    for c in candidates:
        by_source[c['source']].append(c)
    for rows in by_source.values():
        rows.sort(key=lambda c: (-c['similarity'], c['travel_s'], c['id']))
        for rank, candidate in enumerate(rows, 1):
            candidate['rank'] = rank
    return sorted(candidates, key=lambda c: (not c['suggested'], c['ambiguous'], -c['similarity'], c['id']))


def journeys(sightings, candidates):
    """Only reviewed links contribute to journeys and OD; unmatched is unknown."""
    lookup = {s['id']: s for s in sightings}
    following, previous = {}, {}
    for pair in candidates:
        if pair['status'] != 'accepted':
            continue
        source, target = pair['source'], pair['target']
        if source not in lookup or target not in lookup:
            raise ValueError('Pair references an unknown sighting')
        if source in following or target in previous:
            raise ValueError('A sighting can have only one predecessor and one successor')
        if lookup[target]['entry_time'] <= lookup[source]['exit_time']:
            raise ValueError('Journey must move forward in time')
        if lookup[target]['class_id'] != lookup[source]['class_id']:
            raise ValueError('Journey vehicle classes do not agree')
        following[source], previous[target] = target, source
    result = []
    for start in sorted(following):
        if start in previous:
            continue
        path = [start]
        while path[-1] in following:
            path.append(following[path[-1]])
        first, last = lookup[path[0]], lookup[path[-1]]
        result.append(dict(journey_id=hashlib.sha256('|'.join(path).encode()).hexdigest()[:20],
                           origin=first['point_id'], destination=last['point_id'],
                           departure_time=first['exit_time'], arrival_time=last['entry_time'],
                           travel_s=last['entry_time'] - first['exit_time'],
                           class_id=first['class_id'], sightings=path,
                           points=[lookup[key]['point_id'] for key in path], status='reviewed'))
    return result


def review(result, pair_id, decision):
    if decision not in {'accepted', 'rejected', 'pending'}:
        raise ValueError('Unknown review decision')
    pair = next((c for c in result['candidates'] if c['id'] == pair_id), None)
    if pair is None:
        raise ValueError('Unknown pair ID')
    old = pair['status']
    pair['status'] = decision
    try:
        updated = journeys(result['sightings'], result['candidates'])
    except ValueError:
        pair['status'] = old
        raise
    result['journeys'] = updated
    if decision in {'accepted', 'pending'}:
        result.get('source_reviews', {}).pop(pair['source'], None)
