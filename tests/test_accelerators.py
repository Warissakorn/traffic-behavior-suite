import sys
from types import SimpleNamespace
import numpy as np
import pytest

from tbs.accelerators import torch_device
from tbs.models import detector_options
from tbs.reid.features import Appearance


def fake_torch(monkeypatch, available, count=1):
    cuda = SimpleNamespace(is_available=lambda: available, device_count=lambda: count,
                           get_device_name=lambda index: f'Test GPU {index}')
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(cuda=cuda, version=SimpleNamespace(cuda='12.8')))


def test_auto_selects_available_cuda_and_explicit_gpu_is_resolved(monkeypatch):
    fake_torch(monkeypatch, True, 2)
    device, info = torch_device('auto')
    assert device == '0' and info['device'] == 'cuda:0'
    device, info = torch_device('cuda:1')
    assert device == '1' and info['gpu_name'] == 'Test GPU 1'
    with pytest.raises(ValueError, match='GPU 2'):
        torch_device('2')


def test_auto_falls_back_but_explicit_cuda_does_not(monkeypatch):
    fake_torch(monkeypatch, False)
    device, info = torch_device('auto')
    assert device == 'cpu' and info['fallback_reason']
    assert torch_device('cpu')[0] == 'cpu'
    with pytest.raises(ValueError, match='CUDA GPU'):
        torch_device('0')


@pytest.mark.parametrize('device', ['cuda:-1', 'invalid', 'cuda:', '0,1'])
def test_invalid_detector_devices(device):
    with pytest.raises(ValueError):
        torch_device(device)


@pytest.mark.parametrize('half', [1, 'yes', None])
def test_fp16_requires_boolean(half):
    with pytest.raises(ValueError, match='half'):
        detector_options(dict(half=half))


def test_explicit_gpu_without_onnx_does_not_claim_histogram_acceleration():
    with pytest.raises(ValueError, match='ONNX'):
        Appearance(dict(reid_device='0'))
    assert Appearance(dict(reid_device='auto')).metadata['device'] == 'cpu'


def test_real_onnx_auto_cpu_and_explicit_cuda_error(tmp_path):
    pytest.importorskip('onnxruntime')
    pytest.importorskip('onnx')
    import importlib.util
    from pathlib import Path
    path = Path(__file__).parents[1] / 'tools/windows/build.py'
    sys.path.insert(0, str(path.parent))
    try:
        spec = importlib.util.spec_from_file_location('tbs_portable_build', path)
        build = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(build)
        model = tmp_path / 'smoke.onnx'
        build.create_onnx_smoke(model)
    finally:
        sys.path.pop(0)
    extractor = Appearance(dict(reid_model=str(model), input_size=[32, 32], reid_device='auto'))
    result = extractor.extract(np.full((32, 32, 3), 127, np.uint8))
    assert result.size == 16 and np.linalg.norm(result) == pytest.approx(1)
    assert extractor.metadata['backend'] == 'onnxruntime'
    import onnxruntime as ort
    if 'CUDAExecutionProvider' not in ort.get_available_providers():
        assert extractor.metadata['device'] == 'cpu'
        with pytest.raises(ValueError, match='CUDA provider'):
            Appearance(dict(reid_model=str(model), input_size=[32, 32], reid_device='0'))


@pytest.mark.parametrize('requested', ['auto', '0'])
def test_detector_checks_actual_onnx_provider_before_claiming_gpu(requested):
    from tbs.detection import YoloDetector
    detector = YoloDetector.__new__(YoloDetector)
    detector.options = detector_options(dict(device=requested, image_size=64))
    detector.device = '0'
    detector.metadata = dict(device='cuda:0', accelerator='cuda')
    backend = SimpleNamespace(device=SimpleNamespace(type='cpu', index=None), fp16=False,
                              format='onnx', session=SimpleNamespace(get_providers=lambda: ['CPUExecutionProvider']))
    empty = SimpleNamespace(cpu=lambda: [])
    prediction = SimpleNamespace(names={0: 'car'}, boxes=SimpleNamespace(cls=empty, conf=empty, xyxy=empty))
    detector.model = SimpleNamespace(predict=lambda *args, **kwargs: [prediction],
                                     predictor=SimpleNamespace(model=backend))
    if requested == '0':
        with pytest.raises(ValueError, match='backend ใช้ CPU'):
            detector.detect(np.zeros((64, 64, 3), np.uint8))
    else:
        assert detector.detect(np.zeros((64, 64, 3), np.uint8)) == []
        assert detector.metadata['device'] == 'cpu'
        assert detector.metadata['accelerator'] == 'cpu'
        assert detector.metadata['fallback_reason']
