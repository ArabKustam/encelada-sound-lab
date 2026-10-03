"""Sample sources: vanilla Minecraft sounds (from the local game install), the user's `samples/` folder and the
Sound Lab library. Every sample is addressed by a short *reference*:

    mc:note/harp                  file path inside assets/minecraft/sounds (без .ogg)
    mc:entity.zombie.ambient      sound event from sounds.json (первый вариант); mc:entity.zombie.ambient#2 — третий
    samples:drums/kick.wav        file in soundlab/samples/
    library:<id>                  rendered sound from the library
    C:/path/to/file.wav           any audio file (wav/ogg/flac/mp3)

Minecraft folder: env MINECRAFT_DIR, else %APPDATA%/.minecraft.
"""
import json
import os
import re
from functools import lru_cache
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SAMPLES = HERE / 'samples'
LIBRARY = HERE / 'library'
AUDIO_EXT = ('.wav', '.ogg', '.flac', '.mp3', '.aiff', '.aif')

# Note-block samples: which note each file plays at pitch 1.0 (ranges from the Minecraft wiki).
NOTE_BLOCK_ROOTS = {
    'harp': 'F#4', 'harp2': 'F#4', 'pling': 'F#4', 'banjo': 'F#4', 'bit': 'F#4', 'iron_xylophone': 'F#4',
    'bass': 'F#2', 'bassattack': 'F#2', 'didgeridoo': 'F#2', 'guitar': 'F#3', 'flute': 'F#5', 'cow_bell': 'F#5',
    'bell': 'F#6', 'icechime': 'F#6', 'xylobone': 'F#6',
}
NOTE_BLOCK_ALIASES = {'chime': 'icechime', 'xylophone': 'xylobone', 'piano': 'harp', 'cowbell': 'cow_bell'}


class SampleError(ValueError):
    pass


# ----------------------------------------------------------------------------------------------------- minecraft

def minecraft_dir():
    return Path(os.environ.get('MINECRAFT_DIR') or Path(os.environ.get('APPDATA', '~')).expanduser() / '.minecraft')


@lru_cache(maxsize=1)
def _mc_index():
    """{'files': {'note/harp': Path}, 'events': {'block.note_block.harp': [..]}} or empty dicts."""
    assets = minecraft_dir() / 'assets'
    files, events = {}, {}
    indexes = sorted((assets / 'indexes').glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True) \
        if (assets / 'indexes').exists() else []
    for idx in indexes:
        try:
            objects = json.loads(idx.read_text(encoding='utf-8')).get('objects', {})
        except ValueError:
            continue
        if 'minecraft/sounds.json' not in objects:
            continue
        for key, obj in objects.items():
            if key.startswith('minecraft/sounds/') and key.endswith('.ogg'):
                h = obj['hash']
                files[key[len('minecraft/sounds/'):-4]] = assets / 'objects' / h[:2] / h
        h = objects['minecraft/sounds.json']['hash']
        try:
            events = json.loads((assets / 'objects' / h[:2] / h).read_text(encoding='utf-8'))
        except (OSError, ValueError):
            events = {}
        break
    return {'files': files, 'events': events}


def mc_available():
    return bool(_mc_index()['files'])


def mc_event_files(event, depth=0):
    """Sound event → list of file names (resolves `"type": "event"` references)."""
    entry = _mc_index()['events'].get(event)
    if not entry or depth > 4:
        return []
    out = []
    for s in entry.get('sounds', []):
        if isinstance(s, str):
            out.append(s)
        elif s.get('type') == 'event':
            out += mc_event_files(s['name'].replace('minecraft:', ''), depth + 1)
        else:
            out.append(s['name'])
    return [o.replace('minecraft:', '') for o in out]


def resolve(ref, library_dir=None):
    """Reference → Path of an audio file."""
    ref = str(ref).strip()
    if ref.startswith('mc:'):
        name = ref[3:]
        variant = 0
        if '#' in name:
            name, v = name.split('#', 1)
            variant = int(v)
        idx = _mc_index()
        if not idx['files']:
            raise SampleError(f'не нашёл звуки Minecraft в {minecraft_dir()} (задайте MINECRAFT_DIR)')
        nb = name[len('note_block/'):] if name.startswith('note_block/') else None
        if nb is not None:
            name = 'note/' + NOTE_BLOCK_ALIASES.get(nb, nb)
        if name in idx['files']:
            return idx['files'][name]
        files = mc_event_files(name)
        if files:
            return idx['files'][files[variant % len(files)]]
        raise SampleError(f'нет звука Minecraft {name!r} — поищите через search_samples')
    if ref.startswith('tts:'):
        from . import voice
        try:
            return voice.tts_ref_path(ref)
        except voice.VoiceError as exc:
            raise SampleError(str(exc)) from None
    if ref.startswith('samples:'):
        p = (SAMPLES / ref[8:]).resolve()
        if SAMPLES.resolve() not in p.parents or not p.exists():
            raise SampleError(f'нет файла {ref} в {SAMPLES}')
        return p
    if ref.startswith('library:'):
        sid, _, fname = ref.split(':', 1)[1].partition('/')
        folder = Path(library_dir or LIBRARY) / sid
        if fname:                                             # library:<id>/source.mp3 — the original upload
            p = folder / fname
            if '/' in fname or '\\' in fname or '..' in fname or not p.exists():
                raise SampleError(f'нет файла {ref}')
            return p
        for name in ('audio.wav', 'audio.ogg'):
            if (folder / name).exists():
                return folder / name
        sources = sorted(folder.glob('source.*'))
        if sources:
            return sources[0]
        raise SampleError(f'нет звука {ref} в библиотеке')
    p = Path(ref)
    if not p.exists():
        raise SampleError(f'нет файла {ref}')
    return p


@lru_cache(maxsize=256)
def _read(path, mtime):
    import soundfile as sf
    data, sr = sf.read(str(path), dtype='float32', always_2d=True)
    return data, sr


def load(ref, sr=44100, library_dir=None):
    """Reference → stereo float32 array at `sr`."""
    path = resolve(ref, library_dir)
    data, file_sr = _read(str(path), path.stat().st_mtime)
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    data = data[:, :2]
    if file_sr != sr and len(data) > 1:
        n = max(1, int(len(data) * sr / file_sr))
        x = np.linspace(0, len(data) - 1, n)
        data = np.stack([np.interp(x, np.arange(len(data)), data[:, c]) for c in range(2)], 1)
    return np.ascontiguousarray(data, dtype=np.float32)


def default_root(ref):
    """Known pitch of a sample (note blocks), else None."""
    m = re.match(r'^mc:(?:note|note_block)/(\w+)', str(ref))
    if m:
        name = NOTE_BLOCK_ALIASES.get(m.group(1), m.group(1))
        return NOTE_BLOCK_ROOTS.get(name)
    m = re.match(r'^mc:block\.note_block\.(\w+)', str(ref))
    if m:
        return NOTE_BLOCK_ROOTS.get(NOTE_BLOCK_ALIASES.get(m.group(1), m.group(1)))
    return None


# ----------------------------------------------------------------------------------------------------- search

def _score(text, words):
    t = text.lower()
    if not all(w in t for w in words):
        return 0
    return sum(3 if re.search(r'(^|[./_:])' + re.escape(w), t) else 1 for w in words) - len(t) / 200


def search(query='', source='all', limit=40):
    """Find samples by words (all must match). Returns [{'ref', 'kind', 'info'}] best first."""
    words = [w for w in re.split(r'[\s,]+', query.lower()) if w]
    found = []
    if source in ('all', 'mc'):
        idx = _mc_index()
        for ev, entry in idx['events'].items():
            s = _score(ev, words) if words else 1
            if s:
                files = mc_event_files(ev)
                found.append((s + 1, {'ref': f'mc:{ev}', 'kind': 'mc_event', 'variants': len(files),
                                      'subtitle': entry.get('subtitle', '')}))
        for name in idx['files']:
            s = _score(name, words) if words else 0.5
            if s:
                found.append((s, {'ref': f'mc:{name}', 'kind': 'mc_file'}))
    if source in ('all', 'samples') and SAMPLES.exists():
        for p in SAMPLES.rglob('*'):
            if p.suffix.lower() in AUDIO_EXT:
                rel = p.relative_to(SAMPLES).as_posix()
                s = _score(rel, words) if words else 1
                if s:
                    found.append((s + 2, {'ref': f'samples:{rel}', 'kind': 'user_sample'}))
    if source in ('all', 'library') and LIBRARY.exists():
        for meta in LIBRARY.glob('*/meta.json'):
            try:
                m = json.loads(meta.read_text(encoding='utf-8'))
            except ValueError:
                continue
            text = ' '.join([meta.parent.name, m.get('name', ''), ' '.join(m.get('tags', [])), m.get('description', '')])
            s = _score(text, words) if words else 1
            if s:
                found.append((s + 2, {'ref': f'library:{meta.parent.name}', 'kind': 'library',
                                      'seconds': m.get('seconds'), 'tags': m.get('tags', [])}))
    found.sort(key=lambda f: -f[0])
    return [f[1] for f in found[:limit]]


def stats():
    idx = _mc_index()
    user = [p for p in SAMPLES.rglob('*') if p.suffix.lower() in AUDIO_EXT] if SAMPLES.exists() else []
    return {'minecraft_dir': str(minecraft_dir()), 'mc_files': len(idx['files']), 'mc_events': len(idx['events']),
            'user_samples': len(user), 'samples_dir': str(SAMPLES)}
