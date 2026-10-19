"""Offline source/frozen inference checks using local randomly initialized models."""
import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
import tempfile


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--profile', choices=['cpu', 'cuda'])
    parser.add_argument('--onnx-model')
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    try:
        with redirect_stdout(sys.stderr):
            import torch
            import onnxruntime as ort
            from ultralytics import YOLO
            from .models import check_model
            from .diagnostics import report
            from .reid.features import Appearance
            import numpy as np
            torch.set_num_threads(2)
            if args.profile == 'cuda' and torch.version.cuda != '12.8':
                raise ValueError(f'Expected CUDA 12.8 PyTorch, found {torch.version.cuda}')
            if args.profile == 'cpu' and torch.version.cuda is not None:
                raise ValueError('CPU profile must use a CPU PyTorch build')
            if args.profile == 'cuda' and 'CUDAExecutionProvider' not in ort.get_available_providers():
                raise ValueError('CUDA profile is missing ONNX Runtime CUDA provider')
            results = []
            with tempfile.TemporaryDirectory(prefix='tbs-runtime-') as temporary:
                for name in ['yolo11n', 'yolo26n']:
                    model = YOLO(name+'.yaml')
                    path = Path(temporary)/(name+'.pt')
                    model.save(path)
                    result = check_model(path, dict(device=args.device, image_size=64))
                    results.append(dict(result['model'], architecture=name))
            appearance = None
            if args.onnx_model:
                reid_device = 'auto' if args.device == 'cpu' else args.device
                extractor = Appearance(dict(reid_model=args.onnx_model, input_size=[32, 32], reid_device=reid_device))
                vector = extractor.extract(np.full((32, 32, 3), 127, np.uint8))
                if vector.size != 16 or not np.isclose(np.linalg.norm(vector), 1):
                    raise ValueError('Re-ID runtime smoke embedding is invalid')
                appearance = extractor.metadata
            result = dict(status='passed', profile=args.profile, detectors=results,
                          reid=appearance, diagnostics=report(),
                          note='Random local models test runtime compatibility, not detection accuracy')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f'Runtime smoke failed: {type(exc).__name__}: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
