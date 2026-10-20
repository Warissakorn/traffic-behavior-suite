"""Exercise pause/resume in the actual packaged worker, then compare all results."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import pyarrow.parquet as pq
import yaml
from tbs.demo import fixture


def check(worker, environment=None):
    with tempfile.TemporaryDirectory(prefix='tbs-checkpoint-') as folder:
        root = Path(folder)
        site = fixture(root/'input')
        shutil.copyfile(site.parent/'synthetic.mkv', site.parent/'second.mkv')
        config = yaml.safe_load(site.read_text())
        start = datetime.fromisoformat(config['videos'][0]['start_time'].replace('Z', '+00:00'))
        config['videos'].append(dict(path='second.mkv', start_time=(start+timedelta(seconds=5)).isoformat()))
        site.write_text(yaml.safe_dump(config), encoding='utf-8')

        def invoke(extra, expected):
            result = subprocess.run([str(worker), '--output', str(root/'output'), '--session', 'checkpoint-smoke',
                '--control', str(root/'control.json'), *map(str, extra)],
                capture_output=True, text=True, encoding='utf-8', timeout=150, env=environment)
            if result.returncode != expected:
                raise RuntimeError(f'Frozen checkpoint worker exit {result.returncode}: {result.stderr[-3000:]}\n{result.stdout[-2000:]}')
            events = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            return next(Path(event['output']) for event in events if event['type'] == 'started')

        baseline = invoke(['--config', site], 0)
        resumed = invoke(['--config', site, '--pause-after-clips', '1'], 4)
        paused = json.loads((resumed/'manifest.json').read_text(encoding='utf-8'))
        if paused['status'] != 'paused' or paused['clips_done'] != 1:
            raise RuntimeError('Frozen worker failed to commit exactly one clip before pausing')
        invoke(['--resume', resumed], 0)
        report = json.loads((resumed/'manifest.json').read_text(encoding='utf-8'))
        if report['status'] != 'completed' or report['frames'] != 100 or report['clips_done'] != 2:
            raise RuntimeError('Frozen resume did not complete the original run')
        for name in ('frames', 'detections', 'point_passages', 'vehicles', 'trajectories', 'line_crossings'):
            if pq.read_table(baseline/f'{name}.parquet').to_pylist() != pq.read_table(resumed/f'{name}.parquet').to_pylist():
                raise RuntimeError(f'Frozen resumed {name} differs from uninterrupted processing')
        return dict(status='passed', frames=report['frames'], clips=2,
                    comparison='All raw and derived rows match uninterrupted frozen processing')
