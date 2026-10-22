#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Turn the upscaled PNGs of pack_build.py into a pack folder the emulator loads (Vulkan::TexturePack):
BC7/BC5/BC4 DDS files with a full mip chain (texconv) and index.txt lines `<key> <width> <height> <dds path>`.

The key is XXH3-64 of the GNF's tiled mip 0, which is what the game puts in GPU memory: 8x8-block micro
tiles, so the size is the block grid aligned to 8 times the block size. Textures with pow2pad get keys for
both rounding orders. Existing DDS files are kept, so the step can run again while the build continues.

usage: pack_encode.py <game dir> <manifest.csv> <png dir> <texconv.exe> <pack dir>"""
import csv
import struct
import subprocess
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import xxhash
from PIL import Image

from gnf_extract import FORMATS
import game_profile
from pack_scan import Archive

# texconv arguments per kind. Colour mips are filtered in linear light (-srgbi); masks and roughness hold
# plain values. The game decides sRGB per draw, the port shows the pack image the same way.
CODECS = {'normal': ['-f', 'BC5_SNORM', '-x2bias', '-dx10'], 'single': ['-f', 'BC4_UNORM', '-dx10'],
          'linear': ['-f', 'BC7_UNORM', '-dx10'], 'color': ['-f', 'BC7_UNORM_SRGB', '-srgbi']}


def kind(row, linear_suffixes):
    """Grey data in colour formats (the profile's linear_suffixes) gets linear mips: a soft mask stays soft."""
    if row['format'] in ('BC4', 'BC5'):
        return 'single' if row['format'] == 'BC4' else 'normal'
    return 'linear' if row['path'].removesuffix('.gnf').endswith(linear_suffixes) else 'color'


def keys(data):
    q0, q1 = struct.unpack_from('<QQ', data, 0x10)
    width, height = (q1 & 0x3fff) + 1, (q1 >> 14 & 0x3fff) + 1
    block_bytes = FORMATS[q0 >> 52 & 63][0]
    offset = 8 + struct.unpack_from('<I', data, 4)[0]
    grids = {((width + 3) // 4, (height + 3) // 4)}
    if q1 >> 57 & 1:  # pow2pad
        ceil = lambda v: 1 << (v - 1).bit_length()
        grids.add((ceil((width + 3) // 4), ceil((height + 3) // 4)))
        grids.add(((ceil(width) + 3) // 4, (ceil(height) + 3) // 4))
    result = []
    for bw, bh in grids:
        size = (bw + 7) // 8 * 8 * ((bh + 7) // 8 * 8) * block_bytes
        if offset + size <= len(data):
            result.append(xxhash.xxh3_64_intdigest(data[offset:offset + size]))
    return result


def encode(game, rows, png_dir, texconv, pack_dir, jobs=6):
    """DDS files and index.txt in `pack_dir` for the manifest `rows` that have a PNG in `png_dir`."""
    # 1. Encode, one texconv run per folder and kind (outputs keep the folder layout): color as BC7,
    # normal maps as BC5 SNORM from the (n + 1) / 2 PNGs of pack_build.py, BC4 as BC4.
    linear = game_profile.for_game(game).linear_suffixes
    todo = defaultdict(list)
    for row in rows:
        rel = Path(row['path'].removesuffix('.gnf'))
        png, dds = png_dir / rel.with_suffix('.png'), pack_dir / rel.with_suffix('.dds')
        if png.exists() and not dds.exists():
            todo[dds.parent, kind(row, linear)].append(png)
    # texconv works through its files one by one and leaves most of the machine idle: several run at once,
    # on batches of 8 files.
    batches = [(folder, codec, pngs[i:i + 8]) for (folder, codec), pngs in todo.items()
               for i in range(0, len(pngs), 8)]
    total, done = sum(len(b[2]) for b in batches), 0

    def run(batch):
        folder, codec, pngs = batch
        folder.mkdir(parents=True, exist_ok=True)
        subprocess.run([str(texconv), '-nologo', '-y', *CODECS[codec], '-m', '0', '-o', str(folder),
                        *map(str, pngs)], check=True, stdout=subprocess.DEVNULL)
        return len(pngs)

    with ThreadPoolExecutor(jobs) as pool:
        for count in pool.map(run, batches):
            done += count
            if done % 200 < count or done == total:
                print(f'{done}/{total} encoded', flush=True)
    # 2. Index of every DDS present.
    archives, lines = {}, []
    for row in rows:
        rel = Path(row['path'].removesuffix('.gnf')).with_suffix('.dds')
        if not (pack_dir / rel).exists():
            continue
        if row['archive'] not in archives:
            archives[row['archive']] = Archive(game / f'{row["archive"]}.psarc')
        archive = archives[row['archive']]
        width, height = Image.open(png_dir / rel.with_suffix('.png')).size
        for key in keys(archive.read(archive.index[row['path']])):
            lines.append(f'{key:016x} {width} {height} {rel.as_posix()}\n')
    (pack_dir / 'index.txt').write_text(''.join(lines))
    print(f'index: {len(lines)} keys', flush=True)


def main():
    game, manifest, png_dir, texconv, pack_dir = (Path(a) for a in sys.argv[1:6])
    rows = [r for r in csv.DictReader(open(manifest)) if r['decision'] == 'pack']
    encode(game, rows, png_dir, texconv, pack_dir)


if __name__ == '__main__':
    main()
