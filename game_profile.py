# SPDX-License-Identifier: GPL-2.0-or-later
"""Game profiles: what differs per game, in profiles/<id>.json (see README.md, Adding a game).

  name             the game's name, for messages
  title_ids        folder names the game is installed as (CUSA...), used to recognise the game folder
  archives         .psarc base names in load order; a later archive overrides an earlier one
  patch_suffix     an archive's patch has this suffix ("p": trico_001p.psarc) and overrides it
  skip_dirs        path parts of textures that are data, not images (lookup tables, shadow maps, probes)
  keep_dirs        path parts of hand-drawn art (cutscene stills, credits) that stays as the artists made it
  linear_suffixes  name endings of grey data in colour formats (masks, roughness): linear mips, no sRGB

The rest of the tool (GNF, psarc, tiling, upscale, encode) is the same for every PS4 game."""
import json
import sys
from dataclasses import dataclass
from pathlib import Path

PROFILES = Path(__file__).resolve().parent / 'profiles'
_forced = None


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    title_ids: tuple
    archives: tuple
    patch_suffix: str
    skip_dirs: tuple
    linear_suffixes: tuple
    keep_dirs: tuple = ()

    def archive_names(self):
        """Archive names (without .psarc) in override order: each base, then its patch."""
        for base in self.archives:
            yield base
            yield base + self.patch_suffix

    def matches(self, game):
        game = Path(game)
        return game.name.upper() in self.title_ids or any((game / f'{a}.psarc').is_file() for a in self.archives)


def load(name):
    """A profile by id (profiles/<id>.json) or by the path of a .json file."""
    path = Path(name) if name.endswith('.json') else PROFILES / f'{name}.json'
    if not path.is_file():
        sys.exit(f'no game profile {name!r}; available: {", ".join(p.id for p in available())}')
    data = json.loads(path.read_text(encoding='utf-8'))
    return Profile(path.stem, data['name'], tuple(data.get('title_ids', ())), tuple(data['archives']),
                   data.get('patch_suffix', ''), tuple(data.get('skip_dirs', ())), tuple(data.get('linear_suffixes', ())),
                   tuple(data.get('keep_dirs', ())))


def available():
    return [load(str(path)) for path in sorted(PROFILES.glob('*.json'))]


def force(name):
    """Use this profile for every game folder (texpack --profile) instead of recognising it."""
    global _forced
    _forced = load(name) if name and name != 'auto' else None


def for_game(game):
    if _forced:
        return _forced
    for profile in available():
        if profile.matches(game):
            return profile
    sys.exit(f'{game}: no game profile recognises this folder (by its name or its .psarc files); '
             f'pass --profile, or add one in {PROFILES} (README.md, Adding a game)')
