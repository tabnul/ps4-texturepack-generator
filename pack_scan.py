#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""List every GNF in a PS4 game's psarcs (the archives of its game profile) with format, size and tile mode, and decide whether it goes in the
2x texture pack. Writes a CSV manifest (path, archive, format, width, height, tiling, decision, reason).

usage: pack_scan.py <game dir> <out.csv>"""
import csv
import hashlib
import re
import struct
import sys
import zlib
from collections import Counter
from pathlib import Path

import game_profile

NAMES = {35: 'BC1', 36: 'BC2', 37: 'BC3', 38: 'BC4', 39: 'BC5', 40: 'BC6', 41: 'BC7', 10: 'RGBA8', 12: 'RGBA16F', 4: 'R32'}
COLOR = {35, 36, 37, 38, 41}  # BC1/2/3/7 colour and masks, BC4 single channel (roughness, light shafts)


class Archive:
    def __init__(self, path):
        self.f = open(path, 'rb')
        _m, _a, _b, _c, toc_len, esz, count, self.block = struct.unpack('>4sHH4sIIII', self.f.read(28))
        self.f.seek(32)
        toc = self.f.read(toc_len - 32)
        self.ents = [(toc[i * esz:i * esz + 16], struct.unpack('>I', toc[i * esz + 16:i * esz + 20])[0],
                      int.from_bytes(toc[i * esz + 20:i * esz + 25], 'big'), int.from_bytes(toc[i * esz + 25:i * esz + 30], 'big'))
                     for i in range(count)]
        table = toc[count * esz:]
        width = 2
        while (1 << (8 * width)) < self.block:
            width += 1
        self.zsizes = [int.from_bytes(table[i:i + width], 'big') for i in range(0, len(table) - len(table) % width, width)]
        by_md5 = {e[0]: i for i, e in enumerate(self.ents)}
        names = [n for n in re.split('[\n\x00]', self.read(0).decode('utf8', 'replace')) if n]
        self.index = {n.lower(): by_md5[md5] for n in names if (md5 := hashlib.md5(n.upper().encode()).digest()) in by_md5}

    def read(self, index, limit=None):
        _md5, zi, size, offset = self.ents[index]
        want = min(size, limit or size)
        out = bytearray()
        self.f.seek(offset)
        while len(out) < want:
            z = self.zsizes[zi]
            raw = self.f.read(z if z else self.block)
            out += raw if z == 0 else inflate(raw)
            zi += 1
        return bytes(out[:want])


def inflate(raw):
    """A block is stored raw when compression does not shrink it; raw data can start like a zlib header."""
    try:
        return zlib.decompress(raw)
    except zlib.error:
        return raw


def decide(path, fmt, width, height, tiling, normals=False, skip_dirs=()):
    side = max(width, height)
    if any(d in path for d in skip_dirs):  # the game profile's data folders
        return 'skip', 'data dir'
    if fmt not in COLOR and not (normals and fmt == 39):  # 39: BC5 normal map
        return 'skip', f'format {NAMES.get(fmt, fmt)} (data/normal)'
    if side < 256:
        return 'skip', 'small (<256)'
    if width * height > 2048 * 2048:  # under the 4096² budget of pack_build.fit it would gain less than 2x
        return 'skip', 'already large'
    if tiling != 13:
        return 'todo', f'tile mode {tiling}'
    return 'pack', ''


def scan(game, normals=False):
    """Manifest rows [path, archive, format, width, height, tiling, decision, reason] of every GNF;
    `normals` puts the BC5 normal maps in the pack too."""
    profile = game_profile.for_game(game)
    seen = {}
    for name in profile.archive_names():
        path = game / f'{name}.psarc'
        if not path.is_file():
            continue
        archive = Archive(path)
        for entry, index in archive.index.items():
            if entry.endswith('.gnf'):
                seen[entry] = (name, archive, index)  # later archives and patches override
    rows = []
    for entry, (name, archive, index) in sorted(seen.items()):
        head = archive.read(index, 0x20)
        if head[:4] != b'GNF ':
            continue
        q0, q1 = struct.unpack_from('<QQ', head, 0x10)
        fmt, tiling = q0 >> 52 & 63, q1 >> 52 & 31
        width, height = (q1 & 0x3fff) + 1, (q1 >> 14 & 0x3fff) + 1
        rows.append([entry, name, NAMES.get(fmt, fmt), width, height, tiling,
                     *decide(entry, fmt, width, height, tiling, normals, profile.skip_dirs)])
    return rows


def write(rows, out):
    with open(out, 'w', newline='') as f:
        csv.writer(f).writerows([['path', 'archive', 'format', 'width', 'height', 'tiling', 'decision', 'reason'], *rows])


def main():
    game, out = Path(sys.argv[1]), sys.argv[2]
    rows = scan(game)
    write(rows, out)
    print(Counter(r[6] for r in rows), Counter(r[7] for r in rows if r[6] != 'pack'), sep='\n')
    print('pack sides:', Counter(max(r[3], r[4]) for r in rows if r[6] == 'pack'))
    print('pack formats:', Counter(r[2] for r in rows if r[6] == 'pack'))


if __name__ == '__main__':
    main()
