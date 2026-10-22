#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Upscale one texture with several models and build side-by-side comparison crops.

usage: upscale.py <in.png> <models dir> <out dir> [scale=2] [crop x,y,size in source pixels ...]

Each 4x model runs in overlapping tiles (device.py: fp16 on CUDA/ROCm), then the result is resized with Lanczos
to `scale` x the source (2x is the texture pack target). Lanczos on the source is the baseline."""
import sys
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

import device

TILE, PAD = 512, 32


def run(model, image):
    """Tiled inference: `image` HxWx3 float32 0..1 -> (H*s)x(W*s)x3."""
    scale = model.scale
    h, w, _ = image.shape
    out = np.zeros((h * scale, w * scale, 3), np.float32)
    device = next(model.model.parameters()).device
    for y in range(0, h, TILE):
        for x in range(0, w, TILE):
            y0, x0 = max(y - PAD, 0), max(x - PAD, 0)
            y1, x1 = min(y + TILE + PAD, h), min(x + TILE + PAD, w)
            tile = torch.from_numpy(image[y0:y1, x0:x1].transpose(2, 0, 1)).unsqueeze(0).to(device, next(model.model.parameters()).dtype)
            with torch.no_grad():
                result = model(tile).float().clamp(0, 1)[0].cpu().numpy().transpose(1, 2, 0)
            ty, tx = (y - y0) * scale, (x - x0) * scale
            th, tw = min(TILE, h - y) * scale, min(TILE, w - x) * scale
            out[y * scale:y * scale + th, x * scale:x * scale + tw] = result[ty:ty + th, tx:tx + tw]
    return out


def main():
    source, models_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    scale = int(sys.argv[4]) if len(sys.argv) > 4 else 2
    crops = [tuple(int(v) for v in c.split(',')) for c in sys.argv[5:]] or [(0, 0, 256)]
    out_dir.mkdir(parents=True, exist_ok=True)
    original = Image.open(source).convert('RGB')
    size = (original.width * scale, original.height * scale)
    results = {'source (nearest)': original.resize(size, Image.NEAREST),
               'lanczos': original.resize(size, Image.LANCZOS)}
    pixels = np.asarray(original, np.float32) / 255
    for path in sorted(models_dir.glob('*')):
        if path.suffix not in ('.pth', '.safetensors'):
            continue
        model, _ = device.load(path)
        start = time.time()
        big = run(model, pixels)
        image = Image.fromarray((big * 255 + 0.5).astype(np.uint8)).resize(size, Image.LANCZOS)
        print(f'{path.stem}: {model.architecture.name} x{model.scale}, {time.time() - start:.1f} s', flush=True)
        results[path.stem] = image
        del model
    for name, image in results.items():
        image.save(out_dir / f'{source.stem}_{name.replace(" ", "_")}.png')
    # Comparison: one row per crop, one column per method, crops shown at the upscaled resolution.
    names = list(results)
    for index, (cx, cy, cs) in enumerate(crops):
        box = (cx * scale, cy * scale, (cx + cs) * scale, (cy + cs) * scale)
        cell = cs * scale
        sheet = Image.new('RGB', (cell * len(names), cell + 24), 'black')
        draw = ImageDraw.Draw(sheet)
        for column, name in enumerate(names):
            sheet.paste(results[name].crop(box), (column * cell, 24))
            draw.text((column * cell + 6, 6), name, fill='white')
        sheet.save(out_dir / f'{source.stem}_compare_{index}.png')


if __name__ == '__main__':
    main()
