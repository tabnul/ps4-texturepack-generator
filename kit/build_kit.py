"""Builds a ready-to-run generator kit: Python + PyTorch + the generator + texconv in one folder.

Players get the kit as a download (the TLG launcher fetches it on demand); nothing is installed or
compiled on their PC. One kit per system and GPU kind:

  windows-nvidia  CUDA 12.8 (RTX 20 or newer)    linux-nvidia  CUDA 12.8 (RTX 20 or newer)
  windows-amd     DirectML (experimental)         linux-amd     ROCm 7.2 (experimental)
  windows-cpu     CPU only (very slow)            linux-cpu     CPU only (very slow)

The model (4x-UltraSharp, CC BY-NC-SA 4.0) is NOT in the kit: kit.json says where to fetch it from its
author's page and which sha256 it must have.

usage: build_kit.py <os> <gpu> <texconv binary> <out dir> [--version V]

Output in <out dir>: kit-<os>-<gpu>.tar.xz.NNN parts (each under 2 GB, the GitHub release limit) and
kit-<os>-<gpu>.json with the size and sha256 of every part and of the whole archive. Needs `xz` on PATH
(Linux, Git for Windows).
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import threading
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

PYTHON = {  # python-build-standalone, install_only (unpacks to python/)
    'release': '20261124', 'version': '3.12.16',
    'windows': 'x86_64-pc-windows-msvc', 'linux': 'x86_64-unknown-linux-gnu',
}
# Tested versions. AMD on Windows: torch-directml pins its own torch (2.4.1).
TORCH = {
    'nvidia': ['torch==2.11.0', 'torchvision==0.26.0', '--index-url', 'https://download.pytorch.org/whl/cu128'],
    'cpu': ['torch==2.11.0', 'torchvision==0.26.0', '--index-url', 'https://download.pytorch.org/whl/cpu'],
    'amd-linux': ['torch==2.11.0', 'torchvision==0.26.0', '--index-url', 'https://download.pytorch.org/whl/rocm7.2'],
    'amd-windows': ['torch-directml==0.2.5.dev240914'],
}
EXTRA = ['spandrel==0.4.2', 'numpy==2.5.2', 'pillow==12.3.0', 'xxhash==4.0.2']
MODEL = {
    'name': '4x-UltraSharp.safetensors',
    'url': 'https://huggingface.co/Kim2091/UltraSharp/resolve/main/4x-UltraSharp.safetensors',
    'sha256': '36a340b5509b699d2c06cb445ddc1d3d39199ac734d889ed6d7915f60e05bcbc',
    'size': 66864028,
    'author': 'Kim2091', 'license': 'CC BY-NC-SA 4.0',
}
GENERATOR = ['texpack.py', 'device.py', 'game_profile.py', 'gnf_extract.py', 'pack_blend.py', 'pack_build.py',
             'pack_encode.py', 'pack_scan.py', 'upscale.py', 'LICENSE', 'README.md']
PART = 1900 << 20  # GitHub release assets must stay under 2 GiB


def fetch(url, dest):
    print(f'fetch {url}', flush=True)
    with urllib.request.urlopen(url) as src, open(dest, 'wb') as out:
        shutil.copyfileobj(src, out, 1 << 20)


def python_exe(root, system):
    return root / 'python' / ('python.exe' if system == 'windows' else 'bin/python3')


def build_tree(system, gpu, texconv, root, version):
    """Fills `root` with python/, generator/ and kit.json."""
    name = f'cpython-{PYTHON["version"]}+{PYTHON["release"]}-{PYTHON[system]}-install_only.tar.gz'
    archive = root.parent / name
    fetch(f'https://github.com/astral-sh/python-build-standalone/releases/download/{PYTHON["release"]}/{name}',
          archive)
    with tarfile.open(archive) as tar:
        tar.extractall(root, filter='data')
    archive.unlink()
    python = python_exe(root, system)
    pip = [str(python), '-m', 'pip', 'install', '--no-cache-dir', '--no-compile', '--disable-pip-version-check']
    torch = TORCH.get(f'{gpu}-{system}', TORCH.get(gpu))
    # torchvision from the torch index: spandrel needs it, and from PyPI it would swap torch for a CPU build.
    subprocess.run([*pip, *torch], check=True)
    subprocess.run([*pip, *EXTRA], check=True)
    # Byte code is rebuilt on first run; shipping it only costs download size.
    for junk in root.rglob('__pycache__'):
        shutil.rmtree(junk, ignore_errors=True)

    gen = root / 'generator'
    (gen / 'bin').mkdir(parents=True)
    (gen / 'models').mkdir()
    for f in GENERATOR:
        shutil.copy2(REPO / f, gen / f)
    shutil.copytree(REPO / 'profiles', gen / 'profiles')
    tc = gen / 'bin' / ('texconv.exe' if system == 'windows' else 'texconv')
    shutil.copy2(texconv, tc)
    tc.chmod(0o755)
    shutil.copy2(HERE / 'THIRD-PARTY.md', root / 'THIRD-PARTY.md')

    # Check the kit runs before packing it.
    subprocess.run([str(python), '-E', '-s', str(gen / 'texpack.py'), 'info'], check=True)
    versions = subprocess.run([str(python), '-E', '-s', '-c',
                               'import torch, torchvision, spandrel; print(torch.__version__, torchvision.__version__,'
                               ' spandrel.__version__)'], check=True, capture_output=True, text=True).stdout.split()
    kit = {
        'kit': 1, 'version': version, 'os': system, 'gpu': gpu,
        'python': PYTHON['version'], 'torch': versions[0], 'torchvision': versions[1], 'spandrel': versions[2],
        # Command, relative to the kit folder: <python> -E -s <script> make <game> <pack> ...
        'python_exe': python.relative_to(root).as_posix(), 'script': 'generator/texpack.py',
        'model': MODEL, 'model_dir': 'generator/models',
    }
    (root / 'kit.json').write_text(json.dumps(kit, indent=2) + '\n')
    return kit


def pack(root, out, stem):
    """tar | xz -T0, cut into PART-sized pieces; returns the manifest's part list and whole-file hash."""
    xz = subprocess.Popen(['xz', '-T0', '-6', '-c'], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    parts, whole = [], hashlib.sha256()

    def write_tar():
        with tarfile.open(fileobj=xz.stdin, mode='w|') as tar:
            for item in sorted(root.iterdir()):
                tar.add(item, arcname=item.name)
        xz.stdin.close()

    writer = threading.Thread(target=write_tar)
    writer.start()
    current, size, h = None, 0, None
    while chunk := xz.stdout.read(1 << 20):
        whole.update(chunk)
        while chunk:
            if current is None:
                name = f'{stem}.tar.xz.{len(parts):03d}'
                current, size, h = open(out / name, 'wb'), 0, hashlib.sha256()
                parts.append({'name': name})
            take = chunk[:PART - size]
            current.write(take)
            h.update(take)
            size += len(take)
            chunk = chunk[len(take):]
            if size == PART:
                current.close()
                parts[-1].update(size=size, sha256=h.hexdigest())
                current = None
    if current:
        current.close()
        parts[-1].update(size=size, sha256=h.hexdigest())
    writer.join()
    if xz.wait():
        sys.exit('xz failed')
    return parts, whole.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('os', choices=['windows', 'linux'])
    parser.add_argument('gpu', choices=['nvidia', 'amd', 'cpu'])
    parser.add_argument('texconv', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--version', default='dev')
    args = parser.parse_args()
    stem = f'kit-{args.os}-{args.gpu}'
    args.out.mkdir(parents=True, exist_ok=True)
    root = args.out / stem
    if root.exists():
        shutil.rmtree(root)
    root.mkdir()
    kit = build_tree(args.os, args.gpu, args.texconv, root, args.version)
    unpacked = sum(f.stat().st_size for f in root.rglob('*') if f.is_file())
    parts, sha = pack(root, args.out, stem)
    shutil.rmtree(root)
    manifest = {**kit, 'unpacked_size': unpacked, 'archive_sha256': sha,
                'archive_size': sum(p['size'] for p in parts), 'parts': parts}
    (args.out / f'{stem}.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'{stem}: {len(parts)} parts, {manifest["archive_size"] >> 20} MB packed, {unpacked >> 20} MB unpacked')


if __name__ == '__main__':
    main()
