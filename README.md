# PS4 texture pack generator

Makes AI-upscaled texture packs from **your own copy** of a PS4 game. It reads the game's `.psarc`
archives (it never writes to the game folder), decodes the GNF textures, upscales them with an AI
model and writes a pack folder of BC7/BC5 DDS files plus an `index.txt`. A port or emulator that
supports the format swaps the textures in while the game runs.

The tool works the same for every PS4 game. What differs per game (archive names, folders to leave
out) sits in a small **game profile** in `profiles/`. Supported out of the box:

| Profile | Game | Title ID | Uses the pack |
|---|---|---|---|
| `tlg` | The Last Guardian | CUSA03745 | [tabnul/tlg_pc](https://github.com/tabnul/tlg_pc) (Settings > Texture pack) |

No packs are distributed here; see [Sharing](#sharing).

## What you need

| | |
|---|---|
| Windows 10/11 | |
| Python 3.12 | [python.org](https://www.python.org/downloads/), with the *py launcher* option ticked |
| The game folder | e.g. `CUSA03745`, with `eboot.bin` and the `.psarc` files (extracted dump) |
| Disk space | tens of GB for a full 4x pack and its intermediate PNGs (`--clean` removes the PNGs afterwards) |
| A GPU, preferably | see below |

| Hardware | How it runs | Full TLG pack (colour 4x, normal maps 2x) |
|---|---|---|
| NVIDIA (GTX 10xx or newer) | PyTorch + CUDA, half precision | a few hours |
| AMD Radeon, Intel Arc | PyTorch + DirectML (DirectX 12) | slower than CUDA |
| No usable GPU | CPU | ~1 minute per 1024×1024 texture on 16 threads: **days** for a full pack. Fine for a few textures with `--only` |

AMD on Linux, or with AMD's ROCm build of PyTorch on Windows, runs as `cuda` without anything extra;
`setup.ps1 -Gpu amd` installs DirectML because that works on every Radeon.

## Setup (once)

1. Open PowerShell in this folder and run:
   ```powershell
   powershell -ExecutionPolicy Bypass -File setup.ps1
   ```
   It detects your video card (or pass `-Gpu nvidia`, `-Gpu amd` or `-Gpu cpu`), creates a Python
   environment in `.venv`, installs PyTorch and the other packages, and downloads Microsoft's
   `texconv.exe` (DirectXTex, MIT license) into `bin\`.
2. Download the upscale model into `models\`:
   [4x-UltraSharp.safetensors](https://huggingface.co/Kim2091/UltraSharp/resolve/main/4x-UltraSharp.safetensors)
   by Kim2091 (license **CC BY-NC-SA 4.0**: non-commercial use).
3. Check:
   ```
   texpack info
   ```
   It lists the devices it can use and which one it picks, the model, texconv and the game profiles.

## Making a pack

Try a few textures first (a minute or two, even on CPU):
```
texpack make "D:\Games\CUSA03745" "D:\Packs\test" --only bg2/far_ivy
```

Then the full pack:
```
texpack make "D:\Games\CUSA03745" "D:\Packs\UltraSharp 4x"
```

- The game profile is picked from the folder name (title ID) or the archives in it; `--profile` forces one.
- The **pack folder's name** is the name the game or launcher shows.
- **Stop and resume:** press Ctrl+C at any time and run the same command again. Finished textures
  are kept in `<pack>.work\png` and skipped.
- The run prints progress with an estimate of the time left.
- Don't play games while it builds: both want the GPU.

Options (`texpack make --help`):

| Option | Default | |
|---|---|---|
| `--profile ID\|FILE` | **auto** | Game profile: an id from `profiles\` or a `.json` file |
| `--scale 2\|4` | **4** | Colour textures. 4x is visibly sharper close up; 2x halves the time and is ~4x smaller |
| `--normal-scale 0\|2\|4` | **2** | Normal maps (surface detail). 0 leaves them out |
| `--max-size 2048\|4096\|8192` | **4096** | Pixel budget of one upscaled texture, as the side of a square (4096 allows 4096×4096 or 8192×2048). 8192 is 4x the disk and video memory |
| `--jobs N` | **3** | Upscale processes sharing the GPU, each with its own copy of the model. Use 1 on the CPU or with little video memory |
| `--encode-jobs N` | **6** | texconv runs at the same time |
| `--only TEXT` | | Only textures whose game path contains TEXT, e.g. `bg2/`, `chara/` |
| `--device auto\|cuda\|directml\|cpu` | **auto** | Force a device (before `make`: `texpack --device cpu make ...`) |
| `--model FILE` | **4x-UltraSharp** in `models\` | Any 4x model [spandrel](https://github.com/chaiNNer-org/spandrel) loads (`.safetensors`/`.pth`) |
| `--work DIR` | `<pack>.work` | Intermediate PNGs and the texture list |
| `--clean` | off | Delete the intermediate PNGs when done |

### What goes in the pack

Every visual texture from 256 pixels up whose upscale still fits the `--max-size` budget at 2x or
more: colour textures (BC1/2/3/7), single-channel textures (BC4) and, with `--normal-scale`, the BC5
normal maps. Grey data stored in colour formats (masks, specular; the profile's `linear_suffixes`)
gets linear mips so a soft mask stays soft.

Left out:
- the profile's data folders (`skip_dirs`: level data, light maps, cube maps...) and hand-drawn art
  (`keep_dirs`: cutscene stills, credits), which stays as the artists made it;
- uncompressed and float formats, and textures under 256 pixels;
- **already large** textures: those that would not get at least 2x within the `--max-size` budget
  (the pixel count counts, not the shape), or beyond the GPU's 16384 pixels on a side. At the
  default 4096 that is anything with more pixels than 2048×2048; at `--max-size 8192`, 4096×4096
  textures get 2x and go in.

### Size and screen resolution

How much of a texture you actually see depends on your screen resolution. The GPU picks the mip
level that fits the number of screen pixels a surface covers, so the largest upscaled level is only
used when a surface fills more pixels than the level below it: close up, and at high resolutions.

| Screen | `--max-size` |
|---|---|
| 1920×1080 | 4096 (default) is enough; 8192 rarely shows |
| 2560×1440 and up, ultrawide, 4K | 8192 shows on close-ups; it costs 4x the disk and video memory for those textures |

## Game notes

### The Last Guardian (`tlg`)

- **Tested best at 3840×1600:** `--max-size 8192` (colour 4x, normal maps 2x). Compared texture by
  texture against a 4096 pack in game, every texture was the same or better. The full pack is about
  67 GB on disk; the port keeps at most 16 GB of it in video memory.
  ```
  texpack make "D:\Games\CUSA03745" "D:\Packs\UltraSharp 4x 8k" --max-size 8192
  ```
- **The large textures and `--max-size`:** 55 textures already have more pixels than 2048×2048. At
  the default 4096 they are left out; at 8192 they get 2x (each about 85 MB in the pack, 4-8x the
  original; together about 5 GB more):

  | Size | Count | What | At 8192 |
  |---|---|---|---|
  | 4096×4096 | 53 | big set pieces (drawbridges, chain gates, pulleys, village walls, floor masks, statues) and distant-LOD stage textures | 2x: visibly crisper wood and stone up close |
  | 4096×2048, 2048×4096 | 2 | distant-LOD stage textures | 2x |
  | 16384×512 and other 16384-wide strips | 10 | effects (splash, ripples, smoke, dust) and two foliage strips | left out at any size: the GPU limit is 16384 on a side |

- **Artwork stays original** (`keep_dirs`, 152 textures): the pre-rendered cutscene stills
  (`ui/cutscene`), the opening and end credits (`ui/credit_op`, `ui/credit_ed`), the loading
  screens (`ui/loading`) and the five layers of the sea-of-clouds cutscene background. They are
  hand-drawn; an upscaler changes the drawing. To upscale them
  anyway, copy `profiles	lg.json`, empty `keep_dirs` and pass the copy with `--profile`.

## Troubleshooting

| Problem | Fix |
|---|---|
| `setup.ps1`: *Python 3.12 is needed* | Install Python 3.12 (python.org) with the py launcher, run setup again |
| `texpack info` shows only CPU on an NVIDIA card | `setup.ps1 -Gpu nvidia`, update the NVIDIA driver |
| `texpack info` shows only CPU on an AMD card | `setup.ps1 -Gpu amd`, update the Radeon driver (DirectX 12 needed) |
| *No game profile matches* | Pass `--profile`, or add a profile for the game (below) |
| Out of memory on the GPU | Lower `--jobs`, close other GPU programs; the upscaler works in 512-pixel tiles |
| `FAIL <texture>` lines in the log | That texture is skipped; the rest of the pack is fine |

## Adding a game

A profile is a JSON file in `profiles\` (its file name is the id):

```json
{
  "name": "The Last Guardian",
  "title_ids": ["CUSA03745"],
  "archives": ["trico_boot", "trico_001", "trico_002", "trico_003"],
  "patch_suffix": "p",
  "skip_dirs": ["_tmp", "stages/", "probe", "clut", "globalshadow", "cubemap", "lightmap"],
  "linear_suffixes": ["_sp", "_mk", "_mask", "_frenelmask", "_gobo", "_lightshaft", "_dirty", "_rg"],
  "keep_dirs": ["ui/cutscene/", "ui/credit_ed/", "ui/credit_op/", "ui/loading/", "demo/fb2b_c02_sea_of_clouds"]
}
```

| Field | |
|---|---|
| `name` | Shown in `texpack info` and while making a pack |
| `title_ids` | Game folder names that select this profile automatically |
| `archives` | `.psarc` files to read, in load order; later archives override earlier ones |
| `patch_suffix` | A patch archive is `<archive><suffix>.psarc` and overrides its base archive |
| `skip_dirs` | Parts of texture paths to leave out: data that is not seen as an image |
| `linear_suffixes` | File name endings (without `.gnf`) of grey data in colour formats: linear mips |
| `keep_dirs` | Parts of texture paths of hand-drawn art (cutscene stills, credits) to leave as it is. Optional |

Start with `skip_dirs` and `linear_suffixes` empty, make a pack with `--only` on a few folders and
look in the game. `pack_scan.py <game> out.csv [max size]` lists every texture with the decision and the reason.

## Pack format

```
<pack>\index.txt
<pack>\<game path>.dds ...
```

`index.txt` lines are `<key> <width> <height> <dds path>`. The key is the XXH3-64 hash of the
texture's tiled mip 0 as it sits in GPU memory, so a loader matches it whatever file the texture
came from. Width and height are the size of the DDS, the upscaled texture with mips (BC7
sRGB for colour, BC4/BC5 UNORM/SNORM for data and normals).

A loader hashes each texture the game uploads, looks the key up and binds the DDS instead. The
reference implementation is `Vulkan::TexturePack` in tlg_pc
(`gpu/shadps4/video_core/renderer_vulkan/vk_texture_pack.cpp`).

## Scripts

`texpack.py` runs the steps; each also runs on its own:

| Script | Does |
|---|---|
| `game_profile.py` | loads `profiles\*.json`, picks one for a game folder |
| `pack_scan.py` | lists every GNF in the profile's psarcs and decides which go in the pack (`decide`) |
| `pack_build.py` | decodes and detiles a GNF, upscales it, writes PNG |
| `pack_encode.py` | texconv to BC7/BC4/BC5 DDS with mips; writes `index.txt` |
| `device.py` | CUDA / ROCm / DirectML / CPU selection |
| `upscale.py` | compares models on one image (side-by-side crops) |
| `gnf_extract.py`, `pack_blend.py` | GNF to DDS; blends a pack with the originals |

## Sharing

A pack is made from the game's own textures: share the **tool**, not the pack. The UltraSharp
model's licence also rules out commercial use of what it makes.

## License

GPL-2.0-or-later (see `LICENSE`). texconv is Microsoft's DirectXTex (MIT); the model is Kim2091's
UltraSharp (CC BY-NC-SA 4.0). Neither is included in this repository.
