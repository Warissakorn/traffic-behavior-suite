"""Pinned inference runtimes shared by source setup and portable CI builds."""
TORCH_VERSION = '2.7.1'
TORCHVISION_VERSION = '0.22.1'
CUDA_RUNTIME = '12.8'
PYINSTALLER_VERSION = '6.16.0'
ONNX_BUILD_VERSION = '1.17.0'


def runtime_install(profile):
    if profile not in {'cpu', 'cuda'}:
        raise ValueError('Expected cpu or cuda runtime profile')
    variant = 'cpu' if profile == 'cpu' else 'cu128'
    return [f'torch=={TORCH_VERSION}+{variant}', f'torchvision=={TORCHVISION_VERSION}+{variant}',
            '--index-url', f'https://download.pytorch.org/whl/{variant}']


def extras(profile, build=False):
    if profile not in {'cpu', 'cuda'}:
        raise ValueError('Expected cpu or cuda runtime profile')
    values = ['gui', 'detect', 'onnx-runtime' if profile == 'cpu' else 'onnx-gpu']
    if build:
        values.append('dev')
    return ','.join(values)
