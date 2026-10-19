import hashlib
import io
import json

import pytest

from tbs import model_download
from tbs.models import ModelRegistry


def source(monkeypatch, content=b'official model fixture', *, digest=None, size=None):
    checksum = digest or hashlib.sha256(content).hexdigest()
    metadata = dict(tag_name='v-test', assets=[dict(
        name='yolo11n.pt', digest='sha256:' + checksum,
        size=len(content) if size is None else size,
        browser_download_url='https://github.com/ultralytics/assets/releases/download/v-test/yolo11n.pt')])
    requests = []

    def open_url(url):
        requests.append(url)
        return io.BytesIO(json.dumps(metadata).encode() if url == model_download.RELEASE_URL else content)

    monkeypatch.setattr(model_download, '_open', open_url)
    return requests, metadata


def test_download_verifies_registers_and_reuses_cache(tmp_path, monkeypatch):
    calls, _ = source(monkeypatch)
    registry = ModelRegistry(tmp_path / 'models.json')
    updates = []
    first = model_download.download_model('yolo11n', registry, progress=lambda *args: updates.append(args))
    assert not first['cached']
    assert first['record']['sha256'] == hashlib.sha256(b'official model fixture').hexdigest()
    assert updates[-1] == (22, 22)
    second = model_download.download_model('yolo11n', registry)
    assert second['cached']
    assert len(calls) == 3  # two release checks, one actual download
    assert len(registry.records()) == 1


def test_update_keeps_previous_and_custom_weights(tmp_path, monkeypatch):
    registry = ModelRegistry(tmp_path / 'models.json')
    custom = tmp_path / 'custom.pt'
    custom.write_bytes(b'my weights')
    registry.register(custom)
    source(monkeypatch, b'version one')
    first = model_download.download_model('yolo11n', registry)
    source(monkeypatch, b'version two')
    second = model_download.download_model('yolo11n', registry)
    assert first['record']['path'] != second['record']['path']
    assert custom.read_bytes() == b'my weights'
    assert len(registry.records()) == 3


@pytest.mark.parametrize('problem', ['checksum', 'size', 'missing_digest', 'url'])
def test_rejects_bad_download_without_registration(tmp_path, monkeypatch, problem):
    calls, metadata = source(monkeypatch, digest='0' * 64 if problem == 'checksum' else None,
                             size=1 if problem == 'size' else None)
    if problem == 'missing_digest':
        metadata['assets'][0]['digest'] = None
    if problem == 'url':
        metadata['assets'][0]['browser_download_url'] = 'https://example.com/yolo11n.pt'
    registry = ModelRegistry(tmp_path / 'models.json')
    with pytest.raises(ValueError):
        model_download.download_model('yolo11n', registry)
    assert registry.records() == []
    assert not list(tmp_path.rglob('*.part'))
    assert not list(tmp_path.rglob('*.pt'))


def test_cancel_cleans_partial_file(tmp_path, monkeypatch):
    source(monkeypatch)
    registry = ModelRegistry(tmp_path / 'models.json')
    cancelled = False

    def progress(done, total):
        nonlocal cancelled
        cancelled = True

    with pytest.raises(ValueError, match='ยกเลิก'):
        model_download.download_model('yolo11n', registry, progress=progress, cancelled=lambda: cancelled)
    assert registry.records() == []
    assert not list(tmp_path.rglob('*.part'))
