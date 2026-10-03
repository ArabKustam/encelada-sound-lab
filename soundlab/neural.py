"""Neural engines (local, RTX GPU), each in its own venv under Encelada-Sound-Lab/engines/:

- ACE-Step 1.5 (MIT)          — whole songs with real vocals from a caption + lyrics (50+ languages, Japanese too),
                                 cover/restyle of an existing audio (e.g. my own arrangement), repaint a fragment.
                                 Runs as a local HTTP server (started on demand, models stay loaded).
- SoulX-Singer (Apache 2.0)   — a real singing voice that sings MY notes exactly (score → vocal). Used by the
                                 instrument {"singer": "en_female"} in recipes.
- Woosh, Sony AI (CC-BY-NC)   — text → sound effect (scrapes, screams, creatures…). Weights are NON-COMMERCIAL.

Every result is cached in soundlab/cache/ai by a hash of its parameters, so re-rendering a recipe is instant.
"""
import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ENGINES = HERE.parent / 'engines'
CACHE = HERE / 'cache' / 'ai'
ACE_DIR = ENGINES / 'ACE-Step-1.5'
ACE_URL = os.environ.get('ACESTEP_URL', 'http://127.0.0.1:8001')
SOULX_VOICES = {'en_female': 'женский, светлый (по умолчанию)', 'zh_female': 'женский, китайский образец',
                'zh_male': 'мужской, ~175 Гц', 'yue_voice': 'кантонский образец, ниже женского'}


class NeuralError(RuntimeError):
    pass


def _key(*parts):
    return hashlib.sha1(json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:20]


def _run(venv_python, script, job, timeout=3600):
    CACHE.mkdir(parents=True, exist_ok=True)
    jp = CACHE / f'job_{_key(job)}.json'
    jp.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
    from .voice import _system_env
    env = _system_env()
    env['PYTHONIOENCODING'] = 'utf-8'
    r = subprocess.run([str(venv_python), str(script), str(jp)], capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=timeout, stdin=subprocess.DEVNULL, env=env,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if r.returncode:
        raise NeuralError(f'{Path(script).stem} упал: {r.stderr.strip()[-1200:]}')
    return r.stdout


def status():
    """What is installed / running."""
    out = {'soulx_singer': (ENGINES / 'SoulX-Singer/pretrained_models/SoulX-Singer/model.pt').exists(),
           'woosh': (ENGINES / 'Woosh/checkpoints/Woosh-DFlow/weights.safetensors').exists()
           or any((ENGINES / 'Woosh/checkpoints/Woosh-DFlow').glob('*.safetensors')),
           'acestep_installed': (ACE_DIR / '.venv').exists()}
    try:
        out['acestep_server'] = _ace_get('/health').get('data', {})
    except NeuralError:
        out['acestep_server'] = None
    return out


# ----------------------------------------------------------------------------------------------------- SoulX-Singer

def sing_parts(lines, voice='en_female', lang='en', steps=32, cfg=3.0, seed=0, takes=1):
    """lines: list of note lists (each monophonic) → list (per line) of lists (per take) of WAV paths (24 kHz)."""
    if not (ENGINES / 'SoulX-Singer/pretrained_models/SoulX-Singer/model.pt').exists():
        raise NeuralError('SoulX-Singer не установлен (python -m soundlab.install singer)')
    result, parts = [], []
    for li, notes in enumerate(lines):
        paths, todo = [], []
        for t in range(max(1, int(takes))):
            sd = seed + 101 * li + t
            k = _key('soulx', notes, voice, lang, steps, cfg, sd)
            path = CACHE / f'sing_{k}.wav'
            paths.append(path)
            if not path.exists():
                todo.append({'seed': sd, 'out': str(path)})
        result.append(paths)
        if todo:
            parts.append({'notes': notes, 'takes': todo, 'lang': lang})
    if parts:
        CACHE.mkdir(parents=True, exist_ok=True)
        job = {'parts': parts, 'voice': voice, 'lang': lang, 'steps': steps, 'cfg': cfg}
        _run(ENGINES / 'SoulX-Singer/.venv/Scripts/python.exe', ENGINES / 'runners/soulx_sing.py', job)
    return result


def sing(notes, voice='en_female', lang='en', steps=32, cfg=3.0, seed=0, takes=1):
    """notes: [{'start': s, 'dur': s, 'midi': m, 'syl': 'la'}] → list of WAV paths (one per take)."""
    return sing_parts([notes], voice, lang, steps, cfg, seed, takes)[0]


def render_singer_track(track, sr, beat, log=None, detune=None):
    """Recipe notes track with instrument {'singer': voice} → stereo float32. Chords are split into voice lines
    (each line sung separately, like soprano/alto/…); `takes` > 1 doubles every line with other seeds = ensemble."""
    import soundfile as sf
    from .engine import note_to_midi
    from .voice_extra import singable
    inst = track['instrument']
    fallback = singable(track.get('lyrics') or inst.get('lyrics') or 'a', track.get('lang') or inst.get('lang', 'auto'))
    groups, k = [], 0
    for n in sorted(track.get('notes', []), key=lambda n: (n[0], str(n[2]))):
        opts = n[4] if len(n) > 4 and isinstance(n[4], dict) else {}
        m = note_to_midi(n[2]) + float(opts.get('pitch', 0)) + (detune(n[0]) / 100 if detune else 0)
        item = {'start': round(n[0] * beat, 4), 'dur': round(n[1] * beat, 4), 'midi': round(m, 2), 'syl': opts.get('syl')}
        if groups and abs(groups[-1][0]['start'] - item['start']) < 1e-4:
            groups[-1].append(item)
        else:
            groups.append([item])
    if not groups:
        return np.zeros((2, 2), np.float32)
    for g in groups:
        syl = next((x['syl'] for x in g if x['syl']), None) or fallback[k % len(fallback)]
        k += 1
        for x in g:
            x['syl'] = syl
        g.sort(key=lambda x: -x['midi'])                  # top voice first
    n_lines = max(len(g) for g in groups)
    lines = [[g[min(i, len(g) - 1)] for g in groups] for i in range(n_lines)]
    lang = inst.get('lang') or track.get('lang') or 'auto'
    syls = [x['syl'] for x in lines[0]]
    lang = 'en' if lang in ('auto', 'en') and all(s.isascii() for s in syls) else ('zh' if lang == 'zh' else 'ru')
    takes = int(inst.get('takes', 1))
    if log:
        log(f'  нейро-вокал SoulX ({inst.get("singer")}): {len(groups)} нот, голосов в аккорде {n_lines}, дублей {takes}')
    paths = sing_parts(lines, inst.get('singer', 'en_female'), lang, int(inst.get('steps', 32)),
                       float(inst.get('cfg', 3.0)), int(inst.get('seed', 0)), takes)
    end_s = max(x['start'] + x['dur'] for g in groups for x in g)
    total = int((end_s + 2) * sr)
    out = np.zeros((total, 2), np.float32)
    rng = np.random.default_rng(int(inst.get('seed', 0)))
    count = n_lines * takes
    for li, line_paths in enumerate(paths):
        for p in line_paths:
            y, fs = sf.read(str(p), dtype='float32')
            if y.ndim > 1:
                y = y.mean(axis=1)
            det = 0 if count == 1 else rng.normal(0, 6)
            ratio = fs / sr * 2 ** (det / 1200)
            y = np.interp(np.arange(int(len(y) / ratio)) * ratio, np.arange(len(y)), y).astype(np.float32)
            shift = 0 if count == 1 else int(abs(rng.normal(0, 0.012)) * sr)
            pan = 0.0 if count == 1 else float(np.clip(rng.uniform(-0.7, 0.7), -1, 1))
            a = (pan + 1) * np.pi / 4
            n = min(len(y), total - shift)
            g = 1.0 if count == 1 else 1.5 / np.sqrt(count)
            out[shift:shift + n, 0] += y[:n] * np.cos(a) * 1.414 * g
            out[shift:shift + n, 1] += y[:n] * np.sin(a) * 1.414 * g
    return out


# ----------------------------------------------------------------------------------------------------- Woosh

def woosh(prompt, duration=5.0, seed=0, model='fast'):
    """Text → SFX WAV path (48 kHz). model: fast (DFlow, 4 steps) | quality (Flow)."""
    k = _key('woosh2', prompt, round(float(duration), 2), int(seed), model)
    path = CACHE / f'sfx_{k}.wav'
    if not path.exists():
        if not (ENGINES / 'Woosh/.venv').exists():
            raise NeuralError('Woosh не установлен (python -m soundlab.install woosh)')
        job = {'items': [{'prompt': prompt, 'duration': duration, 'seed': seed, 'out': str(path)}], 'model': model}
        _run(ENGINES / 'Woosh/.venv/Scripts/python.exe', ENGINES / 'runners/woosh_sfx.py', job)
    return path


def sfx_ai(p, sr, rng):
    """SFX generator for recipes: {"sfx": "ai", "params": {"prompt": "...", "duration": 5, "seed": 1}}."""
    import soundfile as sf
    path = woosh(p['prompt'], p['duration'], int(p['seed']), p.get('model', 'fast'))
    y, fs = sf.read(str(path), dtype='float32', always_2d=True)
    if fs != sr:
        n = int(len(y) * sr / fs)
        y = np.stack([np.interp(np.linspace(0, len(y) - 1, n), np.arange(len(y)), y[:, c]) for c in range(y.shape[1])], 1)
    return y[:, 0] if y.shape[1] == 1 else y[:, :2].astype(np.float32)


# ----------------------------------------------------------------------------------------------------- ACE-Step

def _ace_get(path):
    try:
        with urllib.request.urlopen(ACE_URL + path, timeout=10) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise NeuralError(f'ACE-Step сервер недоступен: {exc}') from None


def _ace_post(path, body, timeout=60):
    req = urllib.request.Request(ACE_URL + path, data=json.dumps(body).encode(), method='POST',
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raise NeuralError(f'ACE-Step {exc.code}: {exc.read().decode("utf-8", "replace")[:500]}') from None
    except (urllib.error.URLError, OSError) as exc:
        raise NeuralError(f'ACE-Step сервер недоступен: {exc}') from None


def _ace_multipart(path, fields, files, timeout=120):
    """POST multipart/form-data (the API only accepts audio as uploads, not local paths)."""
    import uuid
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        if isinstance(v, bool):
            v = 'true' if v else 'false'
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, fp in files.items():
        fp = Path(fp)
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{fp.name}"\r\n'
                     f'Content-Type: application/octet-stream\r\n\r\n'.encode() + fp.read_bytes() + b'\r\n')
    body = b''.join(parts) + f'--{boundary}--\r\n'.encode()
    req = urllib.request.Request(ACE_URL + path, data=body, method='POST',
                                 headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raise NeuralError(f'ACE-Step {exc.code}: {exc.read().decode("utf-8", "replace")[:500]}') from None
    except (urllib.error.URLError, OSError) as exc:
        raise NeuralError(f'ACE-Step сервер недоступен: {exc}') from None


def ensure_acestep(wait=180):
    """Start the ACE-Step API server if it is not running (XL model + 4B LM on a 24 GB GPU)."""
    try:
        _ace_get('/health')
        return
    except NeuralError:
        pass
    if not (ACE_DIR / '.venv').exists():
        raise NeuralError('ACE-Step не установлен (python -m soundlab.install acestep)')
    from .voice import _system_env
    env = _system_env()
    env.update({'ACESTEP_CONFIG_PATH': os.environ.get('ACESTEP_CONFIG_PATH', 'acestep-v15-xl-turbo'),
                'ACESTEP_LM_MODEL_PATH': os.environ.get('ACESTEP_LM_MODEL_PATH', 'acestep-5Hz-lm-1.7B'),
                'ACESTEP_INIT_LLM': 'true', 'ACESTEP_LM_BACKEND': 'pt', 'PYTHONIOENCODING': 'utf-8'})
    log = open(ENGINES / 'acestep_server.log', 'a', encoding='utf-8')
    subprocess.Popen([str(ACE_DIR / '.venv/Scripts/python.exe'), '-m', 'acestep.api_server'], cwd=str(ACE_DIR), env=env,
                     stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'DETACHED_PROCESS', 0))
    t0 = time.time()
    while time.time() - t0 < wait:
        time.sleep(3)
        try:
            _ace_get('/health')
            return
        except NeuralError:
            continue
    raise NeuralError('ACE-Step сервер не запустился — см. engines/acestep_server.log')


def acestep(caption, lyrics='', duration=60, bpm=None, key=None, language='en', instrumental=False, seed=-1,
            task_type='text2music', src_audio=None, reference_audio=None, cover_strength=1.0, repaint=None,
            thinking=True, steps=8, timesig=None, timeout=3600, log=None):
    """Generate with ACE-Step → WAV path (48 kHz stereo). Cached by parameters (except seed=-1 = random)."""
    params = {'prompt': caption, 'lyrics': lyrics or ('[Instrumental]' if instrumental else ''),
              'audio_duration': float(duration), 'vocal_language': language, 'thinking': bool(thinking),
              'inference_steps': int(steps), 'batch_size': 1, 'audio_format': 'wav', 'task_type': task_type}
    if bpm:
        params['bpm'] = int(bpm)
    if key:
        params['key_scale'] = key
    if timesig:
        params['time_signature'] = str(timesig)
    if instrumental:
        params['instrumental'] = True
    if seed is not None and int(seed) >= 0:
        params.update({'use_random_seed': False, 'seed': int(seed)})
    files = {}
    if src_audio:
        files['src_audio'] = Path(src_audio)
        params['audio_cover_strength'] = float(cover_strength)
    if reference_audio:
        files['reference_audio'] = Path(reference_audio)
    if repaint:
        params['repainting_start'], params['repainting_end'] = float(repaint[0]), float(repaint[1])
    k = _key('ace', params, Path(src_audio).stat().st_mtime if src_audio else 0)
    path = CACHE / f'song_{k}.wav'
    if path.exists() and int(seed if seed is not None else -1) >= 0:
        return path
    ensure_acestep()
    task = _ace_multipart('/release_task', params, files) if files else _ace_post('/release_task', params)
    tid = (task.get('data') or {}).get('task_id')
    if not tid:
        raise NeuralError(f'ACE-Step не принял задачу: {task}')
    t0, last = time.time(), ''
    while time.time() - t0 < timeout:
        time.sleep(2.5)
        res = _ace_post('/query_result', {'task_id_list': [tid]})
        item = (res.get('data') or [{}])[0]
        st = item.get('status')
        if st == 1:
            result = json.loads(item['result']) if isinstance(item.get('result'), str) else item.get('result')
            first = result[0] if isinstance(result, list) else result
            url = first['file']
            if url.startswith('/'):
                url = ACE_URL + url
            CACHE.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(url, timeout=120) as r:
                path.write_bytes(r.read())
            meta = {k2: first.get(k2) for k2 in ('metas', 'seed_value', 'dit_model', 'lm_model', 'lyrics', 'prompt')}
            path.with_suffix('.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
            return path
        if st == 2:
            raise NeuralError(f'ACE-Step: ошибка генерации: {str(item)[:600]}')
        msg = f'ACE-Step: генерация… {int(time.time() - t0)} с'
        if log and msg[:-4] != last:
            log(msg)
            last = msg[:-4]
    raise NeuralError('ACE-Step: не дождался результата')
