"""Sound library: every sound = folder with recipe, rendered audio, pictures and history.

library/<id>/
    recipe.json        — current recipe (source of truth)
    meta.json          — name, tags, author, created/updated, duration, history of recipe versions
    audio.wav / audio.ogg / audio_mono.ogg
    waveform.png, spectrogram.png
    history/<n>.json   — previous recipes (undo/compare)
library/events.jsonl   — what the engine is doing right now (the web app streams it: «смотреть, как создаётся»)
"""
import json
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import analysis, engine

ROOT = Path(__file__).resolve().parent
LIB = ROOT / 'library'
EXPORTS = ROOT / 'exports'
EVENTS = LIB / 'events.jsonl'
_lock = threading.Lock()


def slug(name):
    s = re.sub(r'[^a-z0-9_]+', '_', name.lower().strip())
    return s.strip('_') or 'sound'


def event(sound_id, message, level='info', author=None):
    LIB.mkdir(parents=True, exist_ok=True)
    rec = {'t': time.time(), 'id': sound_id, 'msg': message, 'level': level}
    if author:
        rec['author'] = author
    with _lock, EVENTS.open('a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')


def events_since(offset):
    if not EVENTS.exists():
        return [], 0
    with EVENTS.open('rb') as f:
        f.seek(0, 2)
        size = f.tell()
        if offset > size:
            offset = 0
        f.seek(offset)
        data = f.read()
    lines = [json.loads(l) for l in data.decode('utf-8', 'replace').splitlines() if l.strip()]
    return lines[-400:], size


def list_sounds():
    out = []
    for d in sorted(LIB.glob('*/meta.json'), key=lambda p: -p.stat().st_mtime):
        if d.parent.name == PREVIEW:
            continue
        try:
            meta = json.loads(d.read_text(encoding='utf-8'))
            meta['id'] = d.parent.name
            out.append(meta)
        except ValueError:
            continue
    return out


def get(sound_id):
    folder = LIB / sound_id
    if not (folder / 'recipe.json').exists():
        raise KeyError(f'нет звука {sound_id}')
    return {'id': sound_id, 'recipe': json.loads((folder / 'recipe.json').read_text(encoding='utf-8')),
            'meta': json.loads((folder / 'meta.json').read_text(encoding='utf-8'))}


def waveform_png(x, path, w=900, h=140, markers=None, sr=44100):
    """Waveform; markers = [(seconds, label)] drawn as section lines."""
    img = Image.new('RGB', (w, h), (18, 20, 28))
    d = ImageDraw.Draw(img)
    mono = x.mean(axis=1)
    step = max(1, len(mono) // w)
    for i in range(w):
        seg = mono[i * step:(i + 1) * step]
        if len(seg) == 0:
            break
        a, b = float(seg.min()), float(seg.max())
        d.line([(i, h / 2 - b * h / 2), (i, h / 2 - a * h / 2)], fill=(120, 200, 255))
    for sec, label in markers or []:
        px = int(sec * sr / step)
        d.line([(px, 0), (px, h)], fill=(255, 197, 107))
        d.text((px + 3, 2), str(label), fill=(255, 197, 107))
    img.save(path)


def spectrogram_png(x, sr, path, w=900, h=200):
    mono = x.mean(axis=1)
    n_fft = 2048
    hop = max(256, len(mono) // w)
    frames = []
    win = np.hanning(n_fft)
    for s in range(0, max(1, len(mono) - n_fft), hop):
        frames.append(np.abs(np.fft.rfft(mono[s:s + n_fft] * win)))
    if not frames:
        frames = [np.zeros(n_fft // 2 + 1)]
    spec = np.array(frames).T
    freqs = np.fft.rfftfreq(n_fft, 1 / sr)
    # логарифмическая шкала частот 30 Гц … 16 кГц
    target = np.geomspace(30, min(16000, sr / 2 - 1), h)
    rows = np.searchsorted(freqs, target)
    img = 20 * np.log10(spec[rows[::-1]] + 1e-6)
    img = np.clip((img - img.max() + 70) / 70, 0, 1)
    # палитра «inferno»: чёрный → фиолетовый → красный → оранжевый → светло-жёлтый
    stops = np.array([[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66], [245, 125, 21],
                      [250, 193, 39], [252, 255, 164]], dtype=np.float32)
    pos = img * (len(stops) - 1)
    i0 = np.clip(np.floor(pos).astype(int), 0, len(stops) - 2)
    frac = (pos - i0)[..., None]
    rgb = stops[i0] * (1 - frac) + stops[i0 + 1] * frac
    Image.fromarray(rgb.astype(np.uint8)).resize((w, h)).save(path)


def write_ogg(path, audio, sr):
    """OGG Vorbis кусками: libsndfile падает, если отдать длинный файл одним вызовом."""
    import soundfile as sf
    channels = 1 if audio.ndim == 1 else audio.shape[1]
    with sf.SoundFile(str(path), 'w', sr, channels, format='OGG', subtype='VORBIS') as f:
        for i in range(0, len(audio), 16384):
            f.write(audio[i:i + 16384])


def save_render(sound_id, recipe, author='claude', note=''):
    """Render recipe into library/<id> (new or update). Returns meta."""
    import soundfile as sf
    LIB.mkdir(parents=True, exist_ok=True)
    folder = LIB / sound_id
    folder.mkdir(parents=True, exist_ok=True)
    meta_path = folder / 'meta.json'
    meta = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.exists() else {
        'name': recipe.get('name', sound_id), 'created': time.time(), 'history': [], 'tags': recipe.get('tags', [])}
    event(sound_id, f'{"Claude" if author == "claude" else "Вы"}: рендер «{recipe.get("name", sound_id)}»'
          + (f' — {note}' if note else ''), 'start', author)
    t0 = time.time()
    try:
        audio, sr, report = engine.render(recipe, LIB, log=lambda m: event(sound_id, m))
    except Exception as exc:
        event(sound_id, f'ошибка: {exc}', 'error')
        raise
    # история рецептов
    if (folder / 'recipe.json').exists():
        hist = folder / 'history'
        hist.mkdir(exist_ok=True)
        n = len(list(hist.glob('*.json'))) + 1
        shutil.copy(folder / 'recipe.json', hist / f'{n:03d}.json')
    (folder / 'recipe.json').write_text(json.dumps(recipe, ensure_ascii=False, indent=1), encoding='utf-8')
    write_outputs(folder, audio, sr, report)
    info = analysis.analyze(audio, sr)
    (folder / 'analysis.json').write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding='utf-8')
    meta.update({'name': recipe.get('name', meta.get('name')), 'updated': time.time(), 'seconds': report['seconds'],
                 'tags': recipe.get('tags', meta.get('tags', [])), 'kind': recipe.get('kind', meta.get('kind', 'sound')),
                 'description': recipe.get('description', meta.get('description', '')),
                 'tempo': report.get('tempo'), 'beats': report.get('beats'), 'sections': report.get('sections', [])})
    meta.setdefault('history', []).append({'t': time.time(), 'author': author, 'note': note, 'seconds': report['seconds']})
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
    event(sound_id, f'сохранено за {time.time() - t0:.1f} с → {report["seconds"]} с звука; ' + '; '.join(info['notes']),
          'done', author)
    return {**meta, 'id': sound_id, 'analysis': info}


def write_outputs(folder, audio, sr, report):
    import soundfile as sf
    sf.write(folder / 'audio.wav', audio, sr, subtype='PCM_16')
    write_ogg(folder / 'audio.ogg', audio, sr)
    write_ogg(folder / 'audio_mono.ogg', audio.mean(axis=1), sr)
    beat = 60.0 / float(report.get('tempo') or 60)
    markers = [(s['at'] * beat, s['name']) for s in report.get('sections', [])]
    waveform_png(audio, folder / 'waveform.png', markers=markers, sr=sr)
    spectrogram_png(audio, sr, folder / 'spectrogram.png')


PREVIEW = '_preview'


def preview(recipe, span=None, author='claude'):
    """Render into library/_preview without history (quick checks; span = (from_beat, to_beat))."""
    folder = LIB / PREVIEW
    folder.mkdir(parents=True, exist_ok=True)
    event(PREVIEW, f'{"Claude" if author == "claude" else "Вы"}: предпросмотр «{recipe.get("name", "")}»'
          + (f' доли {span[0]}–{span[1]}' if span else ''), 'start', author)
    try:
        audio, sr, report = engine.render(recipe, LIB, log=lambda m: event(PREVIEW, m), span=span)
    except Exception as exc:
        event(PREVIEW, f'ошибка: {exc}', 'error')
        raise
    (folder / 'recipe.json').write_text(json.dumps(recipe, ensure_ascii=False, indent=1), encoding='utf-8')
    write_outputs(folder, audio, sr, report)
    info = analysis.analyze(audio, sr)
    meta = {'name': 'предпросмотр: ' + str(recipe.get('name', '')), 'updated': time.time(), 'seconds': report['seconds'],
            'tags': ['preview'], 'kind': 'preview', 'history': [], 'span': span}
    (folder / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
    event(PREVIEW, f'предпросмотр готов: {report["seconds"]} с; ' + '; '.join(info['notes']), 'done', author)
    return {**meta, 'id': PREVIEW, 'analysis': info, 'report': report}


def edit(sound_id, set_fields=None, tracks=None, remove_tracks=None):
    """Patch a recipe without resending it. set_fields: top-level keys to replace (tempo, master, arrange…);
    tracks: {track name: fields to merge} (unknown name → new track; `"type"`, notes… as usual);
    remove_tracks: [names]. Returns the new recipe (not rendered)."""
    recipe = get(sound_id)['recipe']
    for k, v in (set_fields or {}).items():
        if v is None:
            recipe.pop(k, None)
        else:
            recipe[k] = v
    by_name = {t.get('name'): t for t in recipe.get('tracks', [])}
    for name, fields in (tracks or {}).items():
        if name in by_name:
            for k, v in fields.items():
                if v is None:
                    by_name[name].pop(k, None)
                else:
                    by_name[name][k] = v
        else:
            recipe.setdefault('tracks', []).append({'name': name, **fields})
    if remove_tracks:
        missing = [n for n in remove_tracks if n not in by_name]
        if missing:
            raise KeyError(f'нет дорожек {missing}; есть: {list(by_name)}')
        recipe['tracks'] = [t for t in recipe['tracks'] if t.get('name') not in set(remove_tracks)]
    return recipe


def create(recipe, author='claude', note=''):
    sid = slug(recipe.get('name', 'sound'))
    if (LIB / sid).exists():
        sid = f'{sid}_{uuid.uuid4().hex[:4]}'
    return save_render(sid, recipe, author, note)


def delete(sound_id):
    folder = LIB / sound_id
    if folder.exists():
        trash = LIB / '.trash' / f'{sound_id}_{int(time.time())}'
        trash.parent.mkdir(exist_ok=True)
        shutil.move(str(folder), str(trash))              # не удаляем насовсем — в корзину
        event(sound_id, 'перемещено в корзину', 'info')


def revert(sound_id, version, author='user'):
    folder = LIB / sound_id
    path = folder / 'history' / f'{int(version):03d}.json'
    recipe = json.loads(path.read_text(encoding='utf-8'))
    return save_render(sound_id, recipe, author, f'возврат к версии {version}')


def export_minecraft(sound_id, key, pack_dir=None, mono=True, stream=False, subtitle=None, variants=1, volume=1.0,
                     pitch=1.0, attenuation=None, pitch_spread=0.0, subfolder='soundlab', pack_format=64):
    """Copy the sound into a resource pack (assets/<ns>/sounds/<subfolder>/...) and register it in sounds.json.

    key: «drugs:halluc.calm_to_horror». Without pack_dir it goes to soundlab/exports/ (a ready resource pack).
    Positional sounds in Minecraft must be mono; long music should use stream=True.
    variants > 1 renders extra versions (other seed, optional ±pitch_spread semitones) — Minecraft picks one at random
    each time the event plays, so repeated SFX don't sound robotic.
    """
    ns, _, event_name = key.partition(':')
    if not event_name:
        ns, event_name = 'drugs', key
    folder = LIB / sound_id
    if not (folder / 'audio.ogg').exists():
        raise KeyError(f'нет звука {sound_id}')
    root = Path(pack_dir) if pack_dir else EXPORTS
    base = slug(event_name)
    out_dir = root / 'assets' / ns / 'sounds' / subfolder
    out_dir.mkdir(parents=True, exist_ok=True)
    files = []
    dest = out_dir / f'{base}.ogg'
    shutil.copy(folder / ('audio_mono.ogg' if mono else 'audio.ogg'), dest)
    files.append(dest)
    variants = max(1, int(variants))
    if variants > 1:
        recipe = get(sound_id)['recipe']
        for k in range(1, variants):
            r = json.loads(json.dumps(recipe))
            r['seed'] = int(r.get('seed', 0)) + 7919 * k
            if pitch_spread:
                shift = float(pitch_spread) * (2 * k / (variants - 1) - 1)
                r.setdefault('master', {}).setdefault('effects', []).append({'type': 'pitch', 'semitones': round(shift, 2)})
            audio, sr, _ = engine.render(r, LIB)
            d = out_dir / f'{base}_{k + 1}.ogg'
            write_ogg(d, audio.mean(axis=1) if mono else audio, sr)
            files.append(d)
    sj = root / 'assets' / ns / 'sounds.json'
    data = json.loads(sj.read_text(encoding='utf-8')) if sj.exists() else {}
    sounds = []
    for f in files:
        s = {'name': f'{ns}:{subfolder}/{f.stem}', 'stream': bool(stream)}
        if volume != 1.0:
            s['volume'] = float(volume)
        if pitch != 1.0:
            s['pitch'] = float(pitch)
        if attenuation:
            s['attenuation_distance'] = int(attenuation)
        sounds.append(s)
    entry = {'sounds': sounds}
    if subtitle:
        entry['subtitle'] = subtitle
    data[event_name] = entry
    sj.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
    mcmeta = root / 'pack.mcmeta'
    if not mcmeta.exists():
        mcmeta.write_text(json.dumps({'pack': {'pack_format': int(pack_format),
                                               'description': 'Encelada Sound Lab sounds'}}, indent=1), encoding='utf-8')
    event(sound_id, f'экспорт в пак: {ns}:{event_name} → {dest}' + (f' (+{variants - 1} вариаций)' if variants > 1 else ''), 'done')
    return {'files': [str(f) for f in files], 'sounds_json': str(sj), 'event': f'{ns}:{event_name}',
            'play_command': f'/playsound {ns}:{event_name} master @s',
            'java': f'player.playSound(player.getLocation(), "{ns}:{event_name}", SoundCategory.MASTER, 1f, 1f);'}


def export_file(sound_id, path, fmt=None, mono=False):
    """Copy the rendered sound anywhere (plugin resources, etc.). fmt: wav | ogg (by extension if omitted)."""
    folder = LIB / sound_id
    path = Path(path)
    fmt = (fmt or path.suffix.lstrip('.') or 'ogg').lower()
    if path.suffix.lower() != '.' + fmt:
        path = path.with_suffix('.' + fmt)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == 'ogg':
        shutil.copy(folder / ('audio_mono.ogg' if mono else 'audio.ogg'), path)
    elif fmt == 'wav':
        import soundfile as sf
        data, sr = sf.read(str(folder / 'audio.wav'), dtype='float32', always_2d=True)
        sf.write(str(path), data.mean(axis=1) if mono else data, sr, subtype='PCM_16')
    else:
        raise ValueError('формат: wav или ogg')
    event(sound_id, f'сохранено в файл {path}', 'done')
    return {'file': str(path)}


def from_file(path, name, kind='music', tags=None, description='', note='', author='claude', extra=None):
    """Put an audio file (e.g. a neural render) into the library as an editable `audio` recipe."""
    import uuid
    sid = f'{slug(name)}_{uuid.uuid4().hex[:4]}'
    folder = LIB / sid
    folder.mkdir(parents=True)
    ext = Path(path).suffix.lower() or '.wav'
    shutil.copy(path, folder / f'source{ext}')
    recipe = {'name': name, 'kind': kind, 'tags': tags or [], 'tempo': 60, 'description': description,
              'tracks': [{'name': 'исходник', 'type': 'audio', 'source': f'library:{sid}/source{ext}', 'gain': 1.0,
                          'effects': []}],
              'master': {'normalize': -1, 'trim': False}}
    if extra:
        recipe.update(extra)
    return save_render(sid, recipe, author, note)
