"""Lazy accelerator discovery and explicit device selection for inference."""
import importlib.util


def torch_device(requested='cpu'):
    """Return an Ultralytics device and evidence; explicit GPU never falls back."""
    requested = str(requested).strip().lower()
    if requested not in {'cpu', 'auto'}:
        value = requested.removeprefix('cuda:')
        if not value.isdecimal():
            raise ValueError('Device ต้องเป็น auto, cpu หรือ CUDA GPU เช่น 0 / cuda:0')
    if requested == 'cpu':
        return 'cpu', dict(requested_device=requested, device='cpu', accelerator='cpu')
    try:
        import torch
    except ImportError as exc:
        if requested == 'auto':
            return 'cpu', dict(requested_device=requested, device='cpu', accelerator='cpu',
                               fallback_reason='PyTorch is not installed')
        raise ValueError('ติดตั้ง PyTorch รุ่น CUDA หรือใช้แพ็กเกจ NVIDIA CUDA ก่อนเลือก GPU') from exc
    count = torch.cuda.device_count() if torch.cuda.is_available() else 0
    if count == 0:
        if requested == 'auto':
            return 'cpu', dict(requested_device=requested, device='cpu', accelerator='cpu',
                               fallback_reason='CUDA GPU/driver or CUDA-enabled PyTorch is unavailable')
        raise ValueError('ไม่พบ NVIDIA CUDA GPU ที่พร้อมใช้ ตรวจ driver และ PyTorch CUDA หรือเลือก cpu/auto')
    index = 0 if requested == 'auto' else int(requested.removeprefix('cuda:'))
    if index >= count:
        raise ValueError(f'ไม่พบ GPU {index}; เครื่องนี้มี CUDA GPU {count} ใบ')
    return str(index), dict(requested_device=requested, device=f'cuda:{index}', accelerator='cuda',
                            gpu_name=torch.cuda.get_device_name(index), cuda_runtime=torch.version.cuda)


def hardware_report():
    result = dict(torch_installed=importlib.util.find_spec('torch') is not None,
                  cuda_available=False, cuda_runtime=None, gpus=[], onnx_providers=[])
    if result['torch_installed']:
        try:
            import torch
            result.update(torch_version=torch.__version__, cuda_runtime=torch.version.cuda,
                          cuda_available=torch.cuda.is_available())
            if result['cuda_available']:
                result['gpus'] = [dict(index=i, name=torch.cuda.get_device_name(i),
                                      memory_bytes=torch.cuda.get_device_properties(i).total_memory)
                                  for i in range(torch.cuda.device_count())]
        except (ImportError, OSError, RuntimeError) as exc:
            result['torch_error'] = str(exc)
    if importlib.util.find_spec('onnxruntime') is not None:
        try:
            import onnxruntime as ort
            result['onnx_providers'] = ort.get_available_providers()
        except (ImportError, OSError, RuntimeError) as exc:
            result['onnx_error'] = str(exc)
    return result
