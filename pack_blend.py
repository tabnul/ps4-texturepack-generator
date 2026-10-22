#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Blend the upscaled PNGs of pack_build.py with the Lanczos-upscaled original, for a pack that keeps the
original's fine grain: out = (1 - amount) * upscaled + amount * original. Alpha stays as upscaled. Existing
outputs are kept.

usage: pack_blend.py <game dir> <manifest.csv> <png dir> <amount 0..1> <out dir>"""
import csv
import sys
from pathlib import Path

from PIL import Image

from pack_build import decode
from pack_scan import Archive


def main():
    game, manifest, png_dir = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    amount, out_dir = float(sys.argv[4]), Path(sys.argv[5])
    rows = [r for r in csv.DictReader(open(manifest)) if r['decision'] == 'pack']
    archives, done = {}, 0
    for row in rows:
        rel = row['path'].removesuffix('.gnf') + '.png'
        source, target = png_dir / rel, out_dir / rel
        if not source.exists() or target.exists():
            continue
        if row['archive'] not in archives:
            archives[row['archive']] = Archive(game / f'{row["archive"]}.psarc')
        archive = archives[row['archive']]
        upscaled = Image.open(source)
        original = decode(archive.read(archive.index[row['path']])).resize(upscaled.size, Image.LANCZOS)
        result = Image.blend(upscaled.convert('RGB'), original.convert('RGB'), amount)
        if upscaled.mode == 'RGBA':
            result.putalpha(upscaled.getchannel('A'))
        target.parent.mkdir(parents=True, exist_ok=True)
        result.save(target)
        done += 1
        if done % 100 == 0:
            print(f'{done} blended', flush=True)
    print(f'finished: {done} blended', flush=True)


if __name__ == '__main__':
    main()
