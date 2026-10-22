#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build the 2x texture pack: every manifest row marked `pack` is extracted, decoded, run through the 4x model
(RGB) and resized to 2x (or kept at 4x) with Lanczos; alpha is upscaled with Lanczos only. Output is <out dir>/<psarc path>.png.
Existing outputs are skipped, so the build can be stopped and resumed.

usage: pack_build.py <game dir> <manifest.csv> <model file> <out dir> [scale 2|4]"""
import csv
import io
import struct
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

import device

from gnf_extract import FORMATS, dds, detile
from pack_scan import Archive
from upscale import run


def decode(data):
    q0, q1 = struct.unpack_from('<QQ', data, 0x10)
    width, height = (q1 & 0x3fff) + 1, (q1 >> 14 & 0x3fff) + 1
    block_bytes, dds_fmt = FORMATS[q0 >> 52 & 63]
    if dds_fmt == 83 and q0 >> 58 & 15 == 1:
        dds_fmt = 84  # BC5 SNORM normal map; Pillow decodes it offset by 128
    offset = 8 + struct.unpack_from('<I', data, 4)[0]
    payload = detile(data, offset, (width + 3) // 4, (height + 3) // 4, block_bytes)
    return Image.open(io.BytesIO(dds(width, height, dds_fmt, payload))).convert('RGBA')


def normal_map(model, image, size):
    """BC5 stores X and Y; the model sees the full normal as a color, the result is renormalized. The PNG
    holds (n + 1) / 2, which pack_encode turns back into SNORM."""
    xy = (np.asarray(image, np.float32)[..., :2] - 128) / 127
    z = np.sqrt(np.clip(1 - (xy ** 2).sum(-1, keepdims=True), 0, 1))
    rgb = run(model, (np.concatenate([xy, z], -1) + 1) / 2)
    rgb = np.asarray(Image.fromarray((rgb * 255 + 0.5).astype(np.uint8)).resize(size, Image.LANCZOS),
                     np.float32) / 255 * 2 - 1
    rgb /= np.maximum(np.linalg.norm(rgb, axis=-1, keepdims=True), 1e-6)
    return Image.fromarray(((rgb + 1) / 2 * 255 + 0.5).astype(np.uint8))


def fit(width, height, scale, max_side):
    """The target size: `scale` times the original, shrunk (keeping the aspect) to at most max_side² pixels
    and 16384 (the GPU limit) on a side. A pixel budget instead of a side limit keeps strips (grass, tile
    atlases, 512x2048) at full scale. Past 4096² the extra detail only shows with the camera against the
    surface, at 4x the memory."""
    shrink = min(1, max_side / (scale * (width * height) ** 0.5), 16384 / (max(width, height) * scale))
    return max(1, round(width * scale * shrink)), max(1, round(height * scale * shrink))


def upscale(model, image, scale, normal, max_side=4096):
    """The upscaled texture: RGB through the model, alpha with Lanczos; normal maps via normal_map."""
    size = fit(image.width, image.height, scale, max_side)
    if normal:
        return normal_map(model, image, size)
    rgb = run(model, np.asarray(image.convert('RGB'), np.float32) / 255)
    result = Image.fromarray((rgb * 255 + 0.5).astype(np.uint8)).resize(size, Image.LANCZOS)
    alpha = image.getchannel('A')
    if alpha.getextrema() != (255, 255):
        result.putalpha(alpha.resize(size, Image.LANCZOS))
    return result


def build(game, rows, model, out_dir, scale_of, max_side=4096):
    """Upscales the manifest `rows` to <out_dir>/<path>.png at scale_of(row), at most max_side; existing PNGs
    are kept."""
    archives = {}
    start, done = time.time(), 0
    todo = [row for row in rows if not (out_dir / (row['path'].removesuffix('.gnf') + '.png')).exists()]
    if len(todo) < len(rows):
        print(f'{len(rows) - len(todo)} of {len(rows)} already done', flush=True)
    for number, row in enumerate(todo, 1):
        target = out_dir / (row['path'].removesuffix('.gnf') + '.png')
        name = row['archive']
        if name not in archives:
            archives[name] = Archive(game / f'{name}.psarc')
        archive = archives[name]
        try:
            image = decode(archive.read(archive.index[row['path']]))
            result = upscale(model, image, scale_of(row), row['format'] == 'BC5', max_side)
            if row['format'] == 'BC4':  # single channel: the model saw it as grey RGB
                result = result.convert('L')
            target.parent.mkdir(parents=True, exist_ok=True)
            result.save(target)
        except Exception as error:  # keep going; failures are listed in the log
            print(f'FAIL {row["path"]}: {error}', flush=True)
            continue
        done += 1
        if done % 25 == 0:
            elapsed = time.time() - start
            left = elapsed / number * (len(todo) - number)
            print(f'{number}/{len(todo)} done, {elapsed / 60:.1f} min, about {left / 60:.0f} min left', flush=True)
    print(f'finished: {done} new in {(time.time() - start) / 60:.1f} min', flush=True)


def _build_part(job):
    game, rows, model_path, device_name, out_dir, scale, normal_scale, max_side = job
    model, _ = device.load(model_path, device_name)
    build(game, rows, model, out_dir, lambda row: normal_scale if row['format'] == 'BC5' else scale, max_side)


def build_jobs(game, rows, model_path, device_name, out_dir, scale, normal_scale, max_side, jobs):
    """build() split over `jobs` processes, each with its own copy of the model. One process leaves the GPU
    waiting while it decodes, resizes and writes PNGs (about 55% busy on an RTX 5090, 3 processes: 95%)."""
    todo = [row for row in rows if not (out_dir / (row['path'].removesuffix('.gnf') + '.png')).exists()]
    parts = [(game, todo[k::jobs], model_path, device_name, out_dir, scale, normal_scale, max_side)
             for k in range(jobs)]
    with ProcessPoolExecutor(jobs) as pool:
        list(pool.map(_build_part, parts))


def main():
    game, manifest, model_path, out_dir = Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4])
    scale = int(sys.argv[5]) if len(sys.argv) > 5 else 2
    rows = [r for r in csv.DictReader(open(manifest)) if r['decision'] == 'pack']
    model, label = device.load(model_path)
    print(label, flush=True)
    build(game, rows, model, out_dir, lambda row: scale)


if __name__ == '__main__':
    main()
