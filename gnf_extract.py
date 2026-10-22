#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Extract one GNF texture from the game's psarcs and write mip 0 as a DDS (BC1/BC3/BC4/BC5/BC7).

usage: gnf_extract.py <game dir> <path inside psarc, e.g. game/textures/bg3/rock_07_u1v1_cl.gnf> <out.dds>

Only tile mode 13 (Thin1DThin) is handled: 8x8-element micro tiles in row order, elements in
Morton order inside a tile (x0 y0 x1 y1 x2 y2). For BC formats an element is one 4x4 block."""
import hashlib
import re
import struct
import sys
import zlib
from pathlib import Path

import game_profile

# data format -> (bytes per 4x4 block, DDS FourCC or DXGI format for a DX10 header)
FORMATS = {35: (8, b'DXT1'), 37: (16, b'DXT5'), 38: (8, 80), 39: (16, 83), 41: (16, 98)}


def find(game, name):
    """Bytes of `name` from the last archive that has it (patches win)."""
    found = None
    for archive in game_profile.for_game(game).archive_names():
        path = Path(game) / f'{archive}.psarc'
        if path.is_file():
            data = read_entry(path, name)
            if data is not None:
                found = data
    return found


def read_entry(path, name):
    with open(path, 'rb') as f:
        _magic, _vmaj, _vmin, _comp, toc_len, esz, count, block = struct.unpack('>4sHH4sIIII', f.read(28))
        f.seek(32)
        toc = f.read(toc_len - 32)
        ents = []
        for i in range(count):
            e = toc[i * esz:(i + 1) * esz]
            ents.append((e[:16], struct.unpack('>I', e[16:20])[0], int.from_bytes(e[20:25], 'big'),
                         int.from_bytes(e[25:30], 'big')))
        table = toc[count * esz:]
        width = 2
        while (1 << (8 * width)) < block:
            width += 1
        zsizes = [int.from_bytes(table[i:i + width], 'big') for i in range(0, len(table) - len(table) % width, width)]

        def read(index):
            _md5, zi, size, offset = ents[index]
            out = bytearray()
            f.seek(offset)
            while len(out) < size:
                z = zsizes[zi]
                raw = f.read(z if z else block)
                out += raw if z == 0 or (len(raw) == min(block, size - len(out)) and raw[:1] != b'\x78') else zlib.decompress(raw)
                zi += 1
            return bytes(out[:size])

        names = {n.lower() for n in re.split('[\n\x00]', read(0).decode('utf8', 'replace')) if n}
        if name.lower() not in names:
            return None
        md5 = hashlib.md5(name.upper().encode()).digest()
        index = next((i for i, e in enumerate(ents) if e[0] == md5), None)
        return read(index) if index is not None else None


def detile(data, offset, blocks_w, blocks_h, block_bytes):
    pitch = (blocks_w + 7) // 8 * 8
    out = bytearray(blocks_w * blocks_h * block_bytes)
    for by in range(blocks_h):
        for bx in range(blocks_w):
            tile = (by // 8) * (pitch // 8) + bx // 8
            x, y = bx & 7, by & 7
            inner = (x & 1) | (y & 1) << 1 | (x & 2) << 1 | (y & 2) << 2 | (x & 4) << 2 | (y & 4) << 3
            src = offset + (tile * 64 + inner) * block_bytes
            dst = (by * blocks_w + bx) * block_bytes
            out[dst:dst + block_bytes] = data[src:src + block_bytes]
    return bytes(out)


def dds(width, height, fmt, payload):
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x80000
    linear = len(payload)
    if isinstance(fmt, bytes):
        pf = struct.pack('<II4s5I', 32, 0x4, fmt, 0, 0, 0, 0, 0)
        dx10 = b''
    else:
        pf = struct.pack('<II4s5I', 32, 0x4, b'DX10', 0, 0, 0, 0, 0)
        dx10 = struct.pack('<5I', fmt, 3, 0, 1, 0)
    header = struct.pack('<4s7I', b'DDS ', 124, flags, height, width, linear, 0, 1) + b'\0' * 44 + pf
    header += struct.pack('<5I', 0x1000, 0, 0, 0, 0)
    return header + dx10 + payload


def main():
    game, name, out = sys.argv[1:4]
    data = find(game, name)
    if data is None or data[:4] != b'GNF ':
        sys.exit(f'{name}: not found or not a GNF')
    q0, q1 = struct.unpack_from('<QQ', data, 0x10)
    fmt = q0 >> 52 & 63
    width, height = (q1 & 0x3fff) + 1, (q1 >> 14 & 0x3fff) + 1
    tiling = q1 >> 52 & 31
    if fmt not in FORMATS or tiling != 13:
        sys.exit(f'{name}: format {fmt} / tile mode {tiling} not handled')
    block_bytes, dds_fmt = FORMATS[fmt]
    offset = 8 + struct.unpack_from('<I', data, 4)[0]  # header: magic, header size, then the T#s
    bw, bh = (width + 3) // 4, (height + 3) // 4
    Path(out).write_bytes(dds(width, height, dds_fmt, detile(data, offset, bw, bh, block_bytes)))
    print(f'{name}: {width}x{height} format {fmt}, data at {offset:#x}, {len(data)} bytes -> {out}')


if __name__ == '__main__':
    main()
