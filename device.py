#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Where the upscale model runs: CUDA (NVIDIA, or AMD with a ROCm build of PyTorch, which also reports
itself as cuda), DirectML (torch-directml: AMD, Intel or any DirectX 12 GPU on Windows) or the CPU.
fp16 only on CUDA/ROCm; DirectML and the CPU run fp32."""
import os

import torch
from spandrel import ModelLoader

NAMES = ('auto', 'cuda', 'directml', 'cpu')


def pick(name='auto'):
    """(torch device, label) for `name` (one of NAMES); auto takes the first that works."""
    if name in ('auto', 'cuda') and torch.cuda.is_available():
        kind = 'ROCm' if getattr(torch.version, 'hip', None) else 'CUDA'
        return torch.device('cuda'), f'{kind}: {torch.cuda.get_device_name(0)}'
    if name in ('auto', 'directml'):
        try:
            import torch_directml
            return torch_directml.device(), f'DirectML: {torch_directml.device_name(torch_directml.default_device())}'
        except ImportError:
            pass
    if name not in ('auto', 'cpu'):
        raise SystemExit(f'device {name} is not available in this Python environment (see setup.ps1 -Gpu)')
    torch.set_num_threads(os.cpu_count() or 1)
    return torch.device('cpu'), f'CPU ({torch.get_num_threads()} threads)'


def load(path, name='auto'):
    """(model, device label): the spandrel model at `path` on the picked device."""
    device, label = pick(name)
    model = ModelLoader().load_from_file(str(path)).to(device).eval()
    if device.type == 'cuda' and model.supports_half:
        model.model.half()
    return model, label
