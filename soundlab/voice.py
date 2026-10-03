"""Singing and speaking with a real human voice.

Syllables are spoken by an installed Windows voice (Irina — Russian, Zira — English, via System.Speech), analyzed with
the WORLD vocoder (pitch, spectral envelope, aperiodicity) and resynthesized on the melody: the vowel is stretched to the
note length, pitch follows the note with vibrato and portamento, formants can be shifted (male/female/child timbre).
Several voices with small differences = a choir that sings words («ля-ля-ля», «ooh», any lyrics).

Also `tts:` sample references for spoken phrases: "tts:Привет, путник" / "tts:en:Hello traveller".
"""
import hashlib
import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CACHE = HERE / 'cache' / 'tts'
FS = 22050
FRAME = 5.0                                                              # ms
VOICES = {'irina': 'Microsoft Irina Desktop', 'zira': 'Microsoft Zira Desktop'}
CYR = re.compile('[а-яёА-ЯЁ]')


class VoiceError(RuntimeError):
    pass


def voice_for(text, voice='auto'):
    if voice in VOICES.values():
        return voice
    if voice and voice != 'auto':
        v = VOICES.get(voice.lower())
        if not v:
            raise VoiceError(f'нет голоса {voice!r}; есть: {", ".join(VOICES)} (auto — по языку)')
        return v
    return VOICES['irina'] if CYR.search(text) else VOICES['zira']


def _path(text, voice, rate):
    h = hashlib.sha1(json.dumps([text, voice, rate], ensure_ascii=False).encode()).hexdigest()[:16]
    return CACHE / f'{h}.wav'


def _system_env():
    """MCP clients start servers with a trimmed environment; SAPI voices need WINDIR & co. to find their data."""
    import os
    env = dict(os.environ)
    root = env.get('SYSTEMROOT') or env.get('SystemRoot') or r'C:\Windows'
    drive = root[:2]
    defaults = {'WINDIR': root, 'SystemRoot': root, 'SystemDrive': drive, 'ProgramFiles': drive + r'\Program Files',
                'ProgramFiles(x86)': drive + r'\Program Files (x86)', 'ProgramW6432': drive + r'\Program Files',
                'CommonProgramFiles': drive + r'\Program Files\Common Files', 'ProgramData': drive + r'\ProgramData',
                'ALLUSERSPROFILE': drive + r'\ProgramData', 'PSModulePath': root + r'\system32\WindowsPowerShell1.0\Modules'}
    upper = {k.upper() for k in env}
    for k, v in defaults.items():
        if k.upper() not in upper:
            env[k] = v
    return env


def tts_many(items):
    """[(text, voice, rate)] → [Path]; speaks only what is not cached yet, in one PowerShell call."""
    CACHE.mkdir(parents=True, exist_ok=True)
    jobs, out = [], []
    for text, voice, rate in items:
        p = _path(text, voice, rate)
        out.append(p)
        if p.exists() and p.stat().st_size < 2000:                    # пустой/битый файл не кэшируем
            p.unlink()
        if not p.exists() and not any(j['path'] == str(p) for j in jobs):
            jobs.append({'text': text, 'voice': voice, 'path': str(p), 'rate': int(rate)})
    if jobs:
        jf = CACHE / 'jobs.json'
        jf.write_text(json.dumps(jobs, ensure_ascii=False), encoding='utf-8')
        r = subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(HERE / 'tts_batch.ps1'), str(jf)],
                           capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL, env=_system_env(),
                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        missing = []
        for j in jobs:
            jp = Path(j['path'])
            if not jp.exists() or jp.stat().st_size < 2000:
                missing.append(j['text'])
                jp.unlink(missing_ok=True)
        if r.returncode or missing:
            raise VoiceError(f'синтез речи Windows не сработал ({r.stderr.strip()[:300]}); не озвучено: {missing[:5]}')
    return out


def tts(text, voice='auto', rate=0):
    return tts_many([(text, voice_for(text, voice), rate)])[0]


def tts_ref_path(ref):
    """'tts:текст' | 'tts:ru:текст' | 'tts:en:text' | 'tts:zira:text' → Path of a WAV."""
    body = ref[4:]
    voice = 'auto'
    m = re.match(r'^(ru|en|irina|zira):(.*)$', body, re.S)
    if m:
        voice = {'ru': 'irina', 'en': 'zira'}.get(m.group(1), m.group(1))
        body = m.group(2)
    if not body.strip():
        raise VoiceError('tts: пустой текст')
    return tts(body.strip(), voice)


# ----------------------------------------------------------------------------------------------------- analysis

@lru_cache(maxsize=256)
def analyze_syllable(path):
    """WORLD analysis of a spoken syllable, trimmed. → dict(f0, sp, ap, voiced span)."""
    import pyworld as pw
    import soundfile as sf
    x, fs = sf.read(str(path), dtype='float64')
    if x.ndim > 1:
        x = x.mean(axis=1)
    if fs != FS:
        x = np.interp(np.linspace(0, len(x) - 1, int(len(x) * FS / fs)), np.arange(len(x)), x)
    x = np.ascontiguousarray(x)
    f0, t = pw.harvest(x, FS, f0_floor=60, f0_ceil=900, frame_period=FRAME)
    sp = pw.cheaptrick(x, f0, t, FS)
    ap = pw.d4c(x, f0, t, FS)
    energy = 10 * np.log10(sp.mean(axis=1) + 1e-12)
    loud = np.nonzero(energy > energy.max() - 45)[0]
    a, b = (loud[0], loud[-1] + 1) if len(loud) else (0, len(f0))
    f0, sp, ap = f0[a:b], sp[a:b], ap[a:b]
    voiced = f0 > 0
    # longest voiced run = the sung part («ля»: л+я)
    best, cur, start = (0, 0), 0, 0
    for i, v in enumerate(list(voiced) + [False]):
        if v:
            if cur == 0:
                start = i
            cur += 1
        else:
            if cur > best[1] - best[0]:
                best = (start, start + cur)
            cur = 0
    if best[1] - best[0] < 4:
        raise VoiceError(f'в слоге {Path(path).name} не нашлось гласной')
    return {'f0': f0, 'sp': sp, 'ap': ap, 'v0': best[0], 'v1': best[1], 'fs': FS}


def _timemap(n_pre, n_voiced, n_post, n_target_voiced):
    """Frame indices: consonants at natural speed, voiced part — attack/decay natural, middle stretched."""
    if n_target_voiced <= n_voiced:
        mid = np.linspace(0, n_voiced - 1, max(2, n_target_voiced))
    else:
        att = int(n_voiced * 0.35)
        dec = int(n_voiced * 0.15)
        core = n_target_voiced - att - dec
        m0, m1 = att, max(att + 1, n_voiced - dec - 1)
        mid = np.concatenate([np.arange(att), np.linspace(m0, m1, max(core, 2)), np.arange(n_voiced - dec, n_voiced)])
    return np.concatenate([np.arange(n_pre), n_pre + mid, n_pre + n_voiced + np.arange(n_post)])


def _warp(sp, factor):
    """Formant shift: factor > 1 — brighter/younger/female, < 1 — darker/male."""
    if abs(factor - 1) < 1e-3:
        return sp
    bins = np.arange(sp.shape[1])
    src = np.clip(bins / factor, 0, sp.shape[1] - 1)
    return np.stack([np.interp(src, bins, row) for row in sp])


def sing_note(syl, hz, dur, prev_hz=None, vibrato=30.0, vib_rate=5.5, formant=1.0, breath=0.0, rng=None, scoop=0.0,
              vib_delay=0.2):
    """One sung syllable. Returns (mono float32 at FS, pre-utterance seconds before the beat)."""
    import pyworld as pw
    rng = rng or np.random.default_rng(0)
    pre = syl['v0']
    post = len(syl['f0']) - syl['v1']
    nv = syl['v1'] - syl['v0']
    target = max(4, int(dur * 1000 / FRAME) - min(post, 20))
    post = min(post, 20)
    tm = _timemap(pre, nv, post, target)
    i0 = np.floor(tm).astype(int)
    fr = (tm - i0)[:, None]
    i1 = np.minimum(i0 + 1, len(syl['f0']) - 1)
    sp = syl['sp'][i0] * (1 - fr) + syl['sp'][i1] * fr
    ap = syl['ap'][i0] * (1 - fr) + syl['ap'][i1] * fr
    voiced = syl['f0'][i0] > 0
    n = len(tm)
    t = (np.arange(n) - pre) * FRAME / 1000
    cents = vibrato * np.sin(2 * np.pi * vib_rate * t + rng.uniform(0, 6)) * np.clip((t - vib_delay) / 0.3, 0, 1)
    if scoop:                                                          # «подъезд» снизу к ноте (аниме, поп)
        cents -= scoop * np.clip(1 - t / 0.09, 0, 1) ** 2
    cents += 6 * np.cumsum(rng.normal(0, 1, n)) / np.sqrt(n)             # живая неровность
    f0 = hz * 2 ** (cents / 1200)
    if prev_hz:
        glide = np.clip(t / 0.07, 0, 1)
        f0 = np.where(t < 0.07, prev_hz * (hz / prev_hz) ** glide, f0)
    f0 = np.where(voiced, f0, 0.0)
    if breath:
        ap = np.clip(ap + breath, 0, 1)
    y = pw.synthesize(np.ascontiguousarray(f0), np.ascontiguousarray(_warp(sp, formant)), np.ascontiguousarray(ap), FS, FRAME)
    fade = min(len(y), int(0.01 * FS))
    y[:fade] *= np.linspace(0, 1, fade)
    y[-fade:] *= np.linspace(1, 0, fade)
    return y.astype(np.float32), pre * FRAME / 1000


def split_lyrics(text):
    return [s for s in re.split(r'[\s\-‐–]+', str(text)) if s]


def render_track(track, sr, beat, log=None, detune=None):
    """Notes track with instrument {'voice': ...} → stereo. Notes carry syllables in opts['syl'] (from `lyrics`)."""
    from .engine import midi_to_hz, note_to_midi
    inst = track['instrument']
    notes = [n for n in track.get('notes', [])]
    if not notes:
        return np.zeros((2, 2), np.float32)
    from .voice_extra import singable
    default = singable(track.get('lyrics') or inst.get('lyrics') or 'ла', track.get('lang') or inst.get('lang', 'auto'))
    syls = []
    k = 0
    last_start = None
    for n in notes:
        opts = n[4] if len(n) > 4 and isinstance(n[4], dict) else {}
        if opts.get('syl'):
            syls.append(opts['syl'])
        else:
            if last_start is not None and abs(n[0] - last_start) < 1e-6 and syls:
                syls.append(syls[-1])                                    # chord: same syllable
            else:
                syls.append(default[k % len(default)])
                k += 1
        last_start = n[0]
    rate = int(inst.get('rate', -2))
    vname = inst.get('voice', 'auto')
    uniq = sorted(set(syls))
    paths = dict(zip(uniq, tts_many([(s, voice_for(s, vname), rate) for s in uniq])))
    count = max(1, int(inst.get('voices', 1)))
    if log:
        log(f'  голос {vname}, {"хор из %d голосов" % count if count > 1 else "соло"}, нот: {len(notes)}, слоги: {" ".join(uniq[:12])}')
    base_formant = float(inst.get('formant', 1.0))
    vib = float(inst.get('vibrato', 30))
    spread = float(inst.get('spread', 1.0))
    total = int((max(n[0] + n[1] for n in notes) * beat + 2) * sr)
    out = np.zeros((total, 2), np.float32)
    timbres = max(1, min(count, int(inst.get('timbres', 3))))
    cache = {}
    for v in range(count):
        rng = np.random.default_rng(1000 + v)
        solo = count == 1
        k_t = v % timbres                                              # тембр: синтезируется один раз на K голосов
        trng = np.random.default_rng(500 + k_t)
        formant = base_formant * (1 if solo else trng.uniform(0.92, 1.1) ** spread)
        det = 0 if solo else rng.normal(0, 9 * spread)
        jitter = 0 if solo else rng.normal(0, 0.018 * spread)
        pan = 0 if solo else np.clip(rng.uniform(-0.8, 0.8) * spread, -1, 1)
        octave = 0
        if not solo and inst.get('octaves') and v % 2 == 1:           # половина хора — мужские голоса октавой ниже
            octave = -12
            formant *= 0.85
        prev = None
        for n, s in zip(notes, syls):
            opts = n[4] if len(n) > 4 and isinstance(n[4], dict) else {}
            m = note_to_midi(n[2]) + octave + (detune(n[0]) / 100 if detune else 0) + float(opts.get('pitch', 0))
            hz = midi_to_hz(m)
            glide = prev if prev and inst.get('portamento', True) and abs(12 * np.log2(hz / prev)) < 7 else None
            key = (s, round(hz, 2), round(n[1] * beat, 3), k_t, octave, round(glide, 1) if glide else None)
            if key not in cache:
                syl = analyze_syllable(str(paths[s]))
                y, pre = sing_note(syl, hz, n[1] * beat, glide, vib * (0.7 + 0.6 * trng.uniform() if not solo else 1),
                                   5.5 + (trng.uniform(-0.6, 0.6) if not solo else 0), formant,
                                   float(inst.get('breath', 0.0)), trng, float(inst.get('scoop', 0.0)),
                                   float(inst.get('vib_delay', 0.2)))
                ratio = FS / sr
                if sr != FS:
                    y = np.interp(np.arange(int(len(y) / ratio)) * ratio, np.arange(len(y)), y).astype(np.float32)
                cache[key] = (y, pre)
            y, pre = cache[key]
            prev = hz
            if det:                                                    # расстройка голоса без нового синтеза
                r = 2 ** (det / 1200)
                y = np.interp(np.arange(int(len(y) / r)) * r, np.arange(len(y)), y).astype(np.float32)
            vel = float(n[3]) if len(n) > 3 else 0.8
            start = int((n[0] * beat - pre + jitter) * sr)
            if start < 0:
                y, start = y[-start:], 0
            end = min(total, start + len(y))
            g = vel * (1.0 if solo else 1.6 / np.sqrt(count))
            a = (pan + 1) * np.pi / 4
            out[start:end, 0] += y[:end - start] * g * np.cos(a) * 1.414
            out[start:end, 1] += y[:end - start] * g * np.sin(a) * 1.414
    return out * 2.5
