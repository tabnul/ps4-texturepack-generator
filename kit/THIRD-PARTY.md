# What is in this kit

This kit runs ps4-texturepack-generator (GPL-2.0-or-later, see `generator/LICENSE`) without installing
anything. It holds other people's work, each under its own license:

| Part | Author | License |
|---|---|---|
| `python/` | Python Software Foundation, built by [python-build-standalone](https://github.com/astral-sh/python-build-standalone) | PSF License (see `python/` license files) |
| PyTorch, torchvision (and on Windows AMD: torch-directml) | PyTorch Foundation / Microsoft | BSD-3-Clause / MIT (see each package's `*.dist-info`) |
| CUDA and ROCm runtime libraries (Nvidia / AMD kits) | NVIDIA / AMD | their redistribution terms, in the `nvidia*` / ROCm package folders |
| spandrel | chaiNNer-org | MIT |
| NumPy, Pillow, xxhash | their authors | BSD / MIT-CMU / BSD |
| `generator/bin/texconv.exe` (Windows) | Microsoft, [DirectXTex](https://github.com/microsoft/DirectXTex) | MIT |
| `generator/bin/texconv` (Linux) | matyalatte, [Texconv-Custom-DLL](https://github.com/matyalatte/Texconv-Custom-DLL) (built from DirectXTex) | MIT |

The upscale model is **not** in the kit. The launcher downloads `4x-UltraSharp.safetensors` from its
author, Kim2091 (<https://huggingface.co/Kim2091/UltraSharp>), into `generator/models/`. It is licensed
CC BY-NC-SA 4.0: no commercial use, and anything shared that is made with it carries the same license.

Thanks to all of them.
