#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""PS4 texture pack generator: reads a game's textures (the game folder is only read), upscales them with
an AI model and writes a texture pack folder. What differs per game is in profiles/ (game_profile.py).
See README.md.

  texpack.py info                      what runs where (GPU, model, texconv) and the game profiles
  texpack.py make <game dir> <pack>    scan, upscale, encode; stop and run again to resume

The pack folder's name is the pack's name in the game."""
import argparse
import csv
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODELS = HERE / 'models'
TEXCONV = HERE / 'bin' / 'texconv.exe'


def default_model():
    found = sorted(p for p in MODELS.glob('*') if p.suffix in ('.safetensors', '.pth'))
    preferred = [p for p in found if p.stem == '4x-UltraSharp']
    return (preferred or found or [None])[0]


def check_inputs(args):
    """Problems that stop `make` before anything runs, as text lines."""
    problems = []
    if not (args.game / 'eboot.bin').is_file() and not list(args.game.glob('*.psarc')):
        problems.append(f'{args.game}: not the game folder (no eboot.bin or .psarc files)')
    if args.model is None or not Path(args.model).is_file():
        problems.append(f'no model: put 4x-UltraSharp.safetensors in {MODELS} or pass --model (README.md)')
    if not Path(args.texconv).is_file():
        problems.append(f'no texconv.exe at {args.texconv}: run setup.ps1 or pass --texconv')
    try:
        args.pack.resolve().relative_to(args.game.resolve())
        problems.append('the pack folder must not be inside the game folder (the game files stay untouched)')
    except ValueError:
        pass
    return problems


def info(args):
    import torch
    import device
    import game_profile
    print(f'Python {sys.version.split()[0]}, PyTorch {torch.__version__}')
    for name in device.NAMES[1:]:
        try:
            print(f'  {name:9} {device.pick(name)[1]}')
        except SystemExit:
            print(f'  {name:9} not available')
    print(f'auto picks: {device.pick(args.device)[1]}')
    model = args.model or default_model()
    print(f'model:   {model or "none (see README.md)"}')
    print(f'texconv: {args.texconv if Path(args.texconv).is_file() else "missing (run setup.ps1)"}')
    for profile in game_profile.available():
        print(f'profile: {profile.id:8} {profile.name} ({", ".join(profile.title_ids)})')


def make(args):
    args.model = args.model or default_model()
    problems = check_inputs(args)
    if problems:
        sys.exit('\n'.join(problems))
    import device
    import game_profile
    from pack_build import build, build_jobs
    from pack_encode import encode
    from pack_scan import scan, write

    game_profile.force(args.profile)
    print(f'game profile: {game_profile.for_game(args.game).name}', flush=True)
    work = args.work or args.pack.with_name(args.pack.name + '.work')
    work.mkdir(parents=True, exist_ok=True)
    # 1. Which textures: colour maps, and the BC5 normal maps unless --normal-scale 0.
    manifest = work / 'manifest.csv'
    write(scan(args.game, normals=args.normal_scale > 0, max_size=args.max_size), manifest)
    packed = [r for r in csv.DictReader(open(manifest)) if r['decision'] == 'pack']
    rows = [r for r in packed if args.only in r['path']]
    normals = sum(r['format'] == 'BC5' for r in rows)
    print(f'{len(rows) - normals} colour textures at {args.scale}x, {normals} normal maps at {args.normal_scale}x', flush=True)
    if not rows:
        sys.exit('nothing to do (check --only)')
    # 2. Upscale to PNGs in the work folder (kept: an interrupted run continues where it stopped).
    start = time.time()
    if args.jobs > 1:
        print(f'{Path(args.model).name} in {args.jobs} processes', flush=True)
        build_jobs(args.game, rows, str(args.model), args.device, work / 'png', args.scale, args.normal_scale,
                   args.max_size, args.jobs)
    else:
        model, label = device.load(args.model, args.device)
        print(f'{Path(args.model).name} x{model.scale} on {label}', flush=True)
        build(args.game, rows, model, work / 'png',
              lambda r: args.normal_scale if r['format'] == 'BC5' else args.scale, args.max_size)
        del model
    # 3. Encode to BC7/BC5 DDS with mipmaps, and the index the game reads.
    # (the index covers every texture with a DDS, also those of earlier --only runs)
    encode(args.game, packed, work / 'png', Path(args.texconv), args.pack, args.encode_jobs)
    size = sum(f.stat().st_size for f in args.pack.rglob('*.dds')) >> 20
    print(f'\ndone in {(time.time() - start) / 60:.0f} min: {args.pack} ({size} MB)')
    print(f'Copy or move the folder "{args.pack.name}" to where your emulator or port reads texture packs.')
    if args.clean:
        shutil.rmtree(work / 'png')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--device', choices=('auto', 'cuda', 'directml', 'cpu'), default='auto',
                        help='cuda: NVIDIA (or AMD with ROCm PyTorch); directml: AMD/Intel on Windows; default auto')
    parser.add_argument('--model', help=f'spandrel model file (default: 4x-UltraSharp in {MODELS})')
    parser.add_argument('--texconv', default=str(TEXCONV), help='DirectXTex texconv.exe (setup.ps1 downloads it)')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('info', help='show the devices, model and texconv found')
    m = sub.add_parser('make', help='build a pack (resumable)')
    m.add_argument('game', type=Path, help='game folder (CUSA..., with eboot.bin and the .psarc files)')
    m.add_argument('--profile', default='auto',
                   help='game profile: an id from profiles/ or a .json file (default auto: recognised by the folder)')
    m.add_argument('pack', type=Path, help='pack folder to write; its name is the name in the game')
    m.add_argument('--scale', type=int, choices=(2, 4), default=4, help='colour textures (default 4)')
    m.add_argument('--normal-scale', type=int, choices=(0, 2, 4), default=2,
                   help='normal maps; 0 leaves them out (default 2)')
    m.add_argument('--max-size', type=int, choices=(2048, 4096, 8192), default=4096,
                   help='size budget of an upscaled texture, as the side of a square: 4096 allows 4096x4096 or '
                        '8192x2048 pixels; 8192 is 4x the disk and video memory (default 4096)')
    m.add_argument('--jobs', type=int, default=3,
                   help='upscale processes sharing the GPU, each with its own copy of the model; one keeps a fast '
                        'GPU only about half busy. Use 1 on the CPU or with little video memory (default 3)')
    m.add_argument('--encode-jobs', type=int, default=6,
                   help='texconv runs at the same time for the BC7/BC5 encode (default 6)')
    m.add_argument('--only',default='', help='only textures whose path contains this text (to try a few first)')
    m.add_argument('--work', type=Path, help='intermediate files (default: <pack>.work next to the pack)')
    m.add_argument('--clean', action='store_true', help='delete the intermediate PNGs when done')
    args = parser.parse_args()
    (info if args.command == 'info' else make)(args)


if __name__ == '__main__':
    main()
