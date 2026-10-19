"""Explicit baseline colour descriptors or a local ONNX vehicle Re-ID model."""
from pathlib import Path
import cv2
import numpy as np
from ..models import file_hash


def normalized(vector):
    vector = np.asarray(vector, dtype=np.float64).reshape(-1)
    norm = np.linalg.norm(vector)
    if not np.isfinite(vector).all() or not np.isfinite(norm) or norm <= 1e-12:
        raise ValueError('Invalid or zero appearance descriptor')
    return vector / norm


class Appearance:
    def __init__(self, options):
        self.net = None
        self.session = None
        model = options.get('reid_model')
        if model:
            model = Path(model)
            if not model.is_file() or model.suffix.lower() != '.onnx':
                raise ValueError('Vehicle Re-ID model must be a local ONNX file')
            self.width, self.height = options.get('input_size', [128, 256])
            self.metadata = dict(method='onnx_vehicle_reid', sha256=file_hash(model),
                                 input_size=[self.width, self.height], preprocessing='RGB ImageNet mean/std')
            requested = options.get('reid_device', 'cpu')
            if requested != 'cpu':
                self._runtime(model, requested)
            if self.session is None:
                try:
                    self.net = cv2.dnn.readNetFromONNX(str(model))
                except cv2.error as exc:
                    raise ValueError(f'Cannot load vehicle Re-ID ONNX: {exc}') from exc
                self.metadata.update(backend='opencv_dnn', device='cpu', requested_device=requested)
        else:
            if options.get('reid_device', 'cpu') not in {'cpu', 'auto'}:
                raise ValueError('เลือกโมเดล Vehicle Re-ID ONNX ก่อนใช้ GPU; histogram สีทำงานบน CPU')
            self.metadata = dict(method='hsv_histogram_v1',
                                 backend='opencv_histogram', device='cpu',
                                 warning='Colour baseline only; not a trained vehicle Re-ID model')

    def extract(self, bgr):
        if bgr.size == 0:
            raise ValueError('Empty vehicle crop')
        if self.net is not None or self.session is not None:
            rgb = cv2.cvtColor(cv2.resize(bgr, (self.width, self.height)), cv2.COLOR_BGR2RGB)
            values = (rgb.astype(np.float32) / 255 - np.array([.485, .456, .406], np.float32))
            values /= np.array([.229, .224, .225], np.float32)
            blob = np.ascontiguousarray(values.transpose(2, 0, 1)[None])
            try:
                if self.session is not None:
                    output = self.session.run(None, {self.session.get_inputs()[0].name: blob})[0]
                else:
                    self.net.setInput(blob)
                    output = self.net.forward()
            except Exception as exc:
                raise ValueError(f'Vehicle Re-ID inference failed; check model input size and supported operators: {exc}') from exc
            if output.ndim not in (1, 2) or (output.ndim == 2 and output.shape[0] != 1) or output.size < 16:
                raise ValueError('ONNX must output one pooled vehicle embedding [1, D], D >= 16')
            return normalized(output)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        hs = cv2.calcHist([hsv], [0, 1], None, [32, 16], [0, 180, 0, 256]).reshape(-1)
        value = cv2.calcHist([hsv], [2], None, [16], [0, 256]).reshape(-1)
        return normalized(np.concatenate([normalized(hs), normalized(value)]))

    def _runtime(self, model, requested):
        explicit = requested != 'auto'
        index = requested.removeprefix('cuda:')
        if explicit and not index.isdecimal():
            raise ValueError('Re-ID device ต้องเป็น cpu, auto หรือ CUDA GPU เช่น 0 / cuda:0')
        try:
            import onnxruntime as ort
        except ImportError as exc:
            if explicit:
                raise ValueError('ติดตั้ง tbs[onnx-gpu] หรือใช้แพ็กเกจ NVIDIA CUDA สำหรับ Re-ID GPU') from exc
            self.metadata['fallback_reason'] = 'ONNX Runtime is not installed; using OpenCV CPU'
            return
        cuda = 'CUDAExecutionProvider' in ort.get_available_providers()
        if explicit and not cuda:
            raise ValueError('ONNX Runtime ไม่มี CUDA provider; ใช้รุ่น onnxruntime-gpu หรือเลือก cpu/auto')
        if cuda:
            # Official PyTorch and ORT CUDA 12 / cuDNN 9 wheels share runtime DLLs.
            try:
                import torch  # noqa: F401
            except ImportError:
                pass
            if hasattr(ort, 'preload_dlls'):
                try:
                    ort.preload_dlls()
                except (OSError, RuntimeError) as exc:
                    if explicit:
                        raise ValueError(f'Cannot preload CUDA/cuDNN runtime: {exc}') from exc
                    cuda = False
        providers = [('CUDAExecutionProvider', {'device_id': int(index) if explicit else 0})] if cuda else []
        providers.append('CPUExecutionProvider')
        try:
            settings = ort.SessionOptions()
            settings.intra_op_num_threads = 4
            session = ort.InferenceSession(str(model), sess_options=settings, providers=providers)
        except Exception as exc:
            if explicit:
                raise ValueError(f'Cannot initialize Re-ID ONNX Runtime: {exc}') from exc
            try:
                session = ort.InferenceSession(str(model), sess_options=settings, providers=['CPUExecutionProvider'])
            except Exception as cpu_exc:
                raise ValueError(f'Cannot initialize Re-ID ONNX Runtime on CPU: {cpu_exc}') from cpu_exc
        actual = session.get_providers()
        active_cuda = 'CUDAExecutionProvider' in actual
        if explicit and not active_cuda:
            raise ValueError('Re-ID CUDA เริ่มทำงานไม่สำเร็จ ตรวจ NVIDIA driver, CUDA/cuDNN DLLs หรือเลือก cpu/auto')
        inputs = session.get_inputs()
        if len(inputs) != 1 or inputs[0].type != 'tensor(float)':
            raise ValueError('Re-ID ONNX requires one float32 image input')
        self.session = session
        self.metadata.update(backend='onnxruntime', providers=actual, requested_device=requested,
                             device=f'cuda:{int(index) if explicit else 0}' if active_cuda else 'cpu')
        if not active_cuda:
            self.metadata['fallback_reason'] = 'CUDA unavailable; ONNX Runtime CPU selected by auto'
