# SPDX-License-Identifier: GPL-2.0-or-later
# Sets up the texture pack maker (texpack.py): a Python 3.12 environment in .venv with PyTorch for
# the GPU, and texconv.exe in bin\. See README.md.
#
#   powershell -ExecutionPolicy Bypass -File setup.ps1 [-Gpu auto|nvidia|amd|cpu]
#
# nvidia: PyTorch with CUDA. amd: torch-directml (DirectX 12; also Intel). cpu: works anywhere, slowly.
# auto looks at the installed video cards. Running it again replaces the environment's PyTorch.
param([ValidateSet('auto', 'nvidia', 'amd', 'cpu')][string]$Gpu = 'auto')
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if ($Gpu -eq 'auto') {
    $cards = (Get-CimInstance Win32_VideoController).Name -join ', '
    $Gpu = if ($cards -match 'NVIDIA') { 'nvidia' } elseif ($cards -match 'AMD|Radeon|Intel\(R\) Arc') { 'amd' } else { 'cpu' }
    Write-Host "Video cards: $cards -> $Gpu"
}

# Python 3.12: torch-directml has no wheels for newer versions (CUDA and CPU would take newer ones too).
if (-not (Test-Path .venv\Scripts\python.exe)) {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw 'Python is not installed. Install Python 3.12 from python.org (with the "py launcher"), then run this again.'
    }
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE) { throw 'Python 3.12 is needed: install it from python.org, then run this again.' }
}
$python = '.venv\Scripts\python.exe'
& $python -m pip install --upgrade pip --quiet
# Through cmd: pip warns on stderr when torch is not installed, which PowerShell 5.1 turns into a stop.
cmd /c "$python -m pip uninstall -y --quiet torch torchvision torch-directml 2>nul"
# torchvision from the same index: spandrel needs it, and from PyPI it would swap torch for a CPU build.
switch ($Gpu) {
    'nvidia' { & $python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128 }
    'amd'    { & $python -m pip install torch-directml }
    'cpu'    { & $python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu }
}
if ($LASTEXITCODE) { throw 'Installing PyTorch failed (see above).' }
& $python -m pip install spandrel numpy pillow xxhash
if ($LASTEXITCODE) { throw 'Installing the packages failed (see above).' }

# texconv (Microsoft DirectXTex, MIT license): PNG -> BC7/BC5 DDS with mipmaps.
New-Item -ItemType Directory -Force bin, models | Out-Null
if (-not (Test-Path bin\texconv.exe)) {
    Invoke-WebRequest https://github.com/microsoft/DirectXTex/releases/latest/download/texconv.exe -OutFile bin\texconv.exe
}

Write-Host ''
& $python texpack.py info
if (-not (Get-ChildItem models -Include *.safetensors, *.pth -Recurse)) {
    Write-Host ''
    Write-Host 'Last step: download the model (CC BY-NC-SA 4.0, by Kim2091) into the models folder:'
    Write-Host '  https://huggingface.co/Kim2091/UltraSharp/resolve/main/4x-UltraSharp.safetensors'
}
