"""Sound Lab engine: renders a JSON *recipe* (music + SFX + effects) into audio.

Everything is deterministic numpy/scipy DSP, so a recipe is the source of truth: the web app, the MCP tools and the
CLI all edit recipes and ask this engine to render them. Recipes may use the compact notation of notation.py (melody
strings, chords, drum grids, sections/parts/arrange, instrument names); render() expands it first. Full syntax: GUIDE.md.
Below is the explicit (expanded) form.

Recipe (all times in beats unless noted, tempo in BPM):
{
  "name": "calm_to_horror", "tempo": 72, "sample_rate": 44100, "channels": 2,
  "tracks": [
    {"name": "melody", "type": "notes", "instrument": {"synth": "musicbox"} | {"gm": 8} | {"gm_drums": true},
     "notes": [[start, length, "C5", velocity 0..1], ...], "gain": 0.8, "pan": 0.0,
     "effects": [{"type": "reverb", "size": 0.7, "mix": 0.35}],
     "automation": {"gain": [[0, 1], [32, 0]], "lowpass": [[24, 12000], [32, 400]], "detune": [[24, 0], [32, -80]],
                    "pan": [[0, -1], [16, 1]]}},
    {"name": "scream", "type": "sfx", "sfx": "scream", "at": 32, "params": {"duration": 2.5},
     "repeat": {"every": 8, "count": 2}, "gain": 0.7, "effects": [...]},
    {"name": "loop", "type": "audio", "source": "library:<id>" | "/path/file.ogg", "at": 0, "loop": 4, ...}
  ],
  "master": {"effects": [...], "normalize": -1.0, "fade_out": 2.0}
}
"""
import hashlib
import json
import math
import os
import re
from pathlib import Path

import numpy as np
from scipy import signal

HERE = Path(__file__).resolve().parent
SOUNDFONTS = HERE / 'soundfonts'
NOTE_RE = re.compile(r'^([A-Ga-g])([#b]?)(-?\d+)$')
NOTE_BASE = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}


class RecipeError(ValueError):
    pass


# ----------------------------------------------------------------------------------------------------- helpers

def note_to_midi(note):
    if isinstance(note, (int, float)):
        return float(note)
    m = NOTE_RE.match(str(note).strip())
    if not m:
        raise RecipeError(f'не понимаю ноту {note!r} (пример: C4, F#3, Bb5 или число MIDI)')
    n = NOTE_BASE[m.group(1).upper()] + (1 if m.group(2) == '#' else -1 if m.group(2) == 'b' else 0)
    return float(n + 12 * (int(m.group(3)) + 1))


def midi_to_hz(m):
    return 440.0 * 2.0 ** ((m - 69.0) / 12.0)


def db(x):
    return 10 ** (x / 20.0)


def stereo(x):
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        return np.stack([x, x], axis=1)
    return x


def pan_stereo(mono, pan):
    """Equal-power pan; pan may be a scalar or an array per sample."""
    pan = np.clip(pan, -1, 1)
    a = (pan + 1) * math.pi / 4
    return np.stack([mono * np.cos(a), mono * np.sin(a)], axis=1).astype(np.float32)


def envelope(n, sr, attack=0.01, decay=0.1, sustain=0.7, release=0.3, hold=None):
    """ADSR; `hold` = seconds the key is held (release starts after it)."""
    hold = n / sr if hold is None else hold
    t = np.arange(n) / sr
    env = np.empty(n, dtype=np.float32)
    a = max(attack, 1e-4)
    d = max(decay, 1e-4)
    env[:] = sustain
    env = np.where(t < a, t / a, env)
    dm = (t >= a) & (t < a + d)
    env = np.where(dm, 1 - (1 - sustain) * (t - a) / d, env)
    level_at_release = np.interp(hold, [0, a, a + d, 1e9], [0, 1, sustain, sustain])
    rel = t >= hold
    env = np.where(rel, level_at_release * np.exp(-(t - hold) / max(release, 1e-3) * 4.6), env)
    return env.astype(np.float32)


def rng_for(*keys):
    """Deterministic RNG (hashlib, not hash(): str hashes change between Python runs)."""
    digest = hashlib.sha1(json.dumps(keys, sort_keys=True, default=str).encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:4], 'little'))


def lowpass(x, cutoff, sr, order=2):
    cutoff = float(np.clip(cutoff, 20, sr * 0.45))
    b, a = signal.butter(order, cutoff / (sr / 2), 'low')
    return signal.lfilter(b, a, x, axis=0).astype(np.float32)


def highpass(x, cutoff, sr, order=2):
    cutoff = float(np.clip(cutoff, 10, sr * 0.45))
    b, a = signal.butter(order, cutoff / (sr / 2), 'high')
    return signal.lfilter(b, a, x, axis=0).astype(np.float32)


def bandpass(x, center, q, sr):
    center = float(np.clip(center, 30, sr * 0.45))
    b, a = signal.iirpeak(center / (sr / 2), max(q, 0.3))
    return signal.lfilter(b, a, x, axis=0).astype(np.float32)


def additive(freqs, amps, decays, n, sr, phases=None):
    """Sum of decaying partials, vectorised. decays in 1/s (0 = none)."""
    t = np.arange(n, dtype=np.float32) / sr
    out = np.zeros(n, dtype=np.float32)
    for i, (f, a, d) in enumerate(zip(freqs, amps, decays)):
        if f >= sr * 0.45 or a <= 0:
            continue
        ph = 0.0 if phases is None else phases[i]
        out += a * np.sin(2 * np.pi * f * t + ph) * (np.exp(-d * t) if d > 0 else 1.0)
    return out


def bl_saw(freq, n, sr, vibrato=0.0, vib_rate=5.0):
    """Band-limited sawtooth by additive synthesis (freq may be modulated by vibrato in semitones)."""
    t = np.arange(n, dtype=np.float32) / sr
    fm = freq * (2 ** (vibrato * np.sin(2 * np.pi * vib_rate * t) / 12)) if vibrato else np.full(n, freq, np.float32)
    phase = 2 * np.pi * np.cumsum(fm) / sr
    out = np.zeros(n, dtype=np.float32)
    kmax = int(min(48, (sr * 0.45) / max(freq, 1)))
    for k in range(1, max(kmax, 1) + 1):
        out += np.sin(k * phase) / k
    return out * 0.6


# ----------------------------------------------------------------------------------------------------- instruments
# Each instrument: fn(freq, hold_seconds, velocity, sr, params, rng) -> mono float32 (includes release tail)

def inst_sine(f, hold, vel, sr, p, rng):
    n = int((hold + p.get('release', 0.3)) * sr)
    return additive([f], [1], [0], n, sr) * envelope(n, sr, p.get('attack', 0.01), 0.1, 0.9, p.get('release', 0.3), hold) * vel


def inst_saw(f, hold, vel, sr, p, rng):
    n = int((hold + p.get('release', 0.3)) * sr)
    x = bl_saw(f, n, sr, p.get('vibrato', 0), p.get('vib_rate', 5))
    x = lowpass(x, p.get('cutoff', 4000), sr)
    return x * envelope(n, sr, p.get('attack', 0.01), 0.2, 0.7, p.get('release', 0.3), hold) * vel


def inst_square(f, hold, vel, sr, p, rng):
    n = int((hold + p.get('release', 0.2)) * sr)
    ks = range(1, int(min(40, sr * 0.45 / f)) + 1, 2)
    x = additive([f * k for k in ks], [1 / k for k in ks], [0] * 40, n, sr) * 0.8
    return x * envelope(n, sr, 0.005, 0.1, 0.6, p.get('release', 0.2), hold) * vel


def inst_triangle(f, hold, vel, sr, p, rng):
    n = int((hold + p.get('release', 0.3)) * sr)
    ks = list(range(1, int(min(30, sr * 0.45 / f)) + 1, 2))
    x = additive([f * k for k in ks], [((-1) ** i) / (k * k) for i, k in enumerate(ks)], [0] * 30, n, sr)
    return x * envelope(n, sr, 0.01, 0.1, 0.8, p.get('release', 0.3), hold) * vel


def inst_musicbox(f, hold, vel, sr, p, rng):
    """Music-box tine: bright inharmonic partials, fast decay (C418 «Sweden»-like lullaby tone)."""
    length = p.get('length', 2.5)
    n = int(length * sr)
    ratios = [1.0, 2.0, 3.99, 5.43, 8.9]
    amps = [1.0, 0.35, 0.22, 0.12, 0.05]
    decays = [1.6, 2.6, 5.0, 8.0, 12.0]
    x = additive([f * r for r in ratios], amps, decays, n, sr, rng.uniform(0, 6.28, 5))
    click = rng.normal(0, 1, n).astype(np.float32) * np.exp(-np.arange(n) / (0.002 * sr)) * 0.05
    return (x + highpass(click, 3000, sr)) * vel * 0.6


def inst_piano(f, hold, vel, sr, p, rng):
    """Soft piano: slightly inharmonic partials, two detuned strings, hammer thump, damper release."""
    n = int((min(hold, 6) + p.get('release', 0.6)) * sr)
    B = 0.0004
    ks = np.arange(1, int(min(24, sr * 0.4 / f)) + 1)
    freqs = f * ks * np.sqrt(1 + B * ks * ks)
    bright = 0.6 + 0.8 * vel
    amps = (1 / ks ** (2.2 - bright)) * np.exp(-ks * 0.08)
    decay = 0.6 + ks * 0.35 + f / 900
    x = additive(freqs, amps, decay, n, sr) + additive(freqs * 1.0015, amps * 0.6, decay * 1.1, n, sr)
    t = np.arange(n) / sr
    x *= np.where(t > hold, np.exp(-(t - hold) * 9.0), 1.0)
    thump = lowpass(rng.normal(0, 1, n).astype(np.float32) * np.exp(-t / 0.01), 800, sr) * 0.3
    return (x * 0.35 + thump) * vel


def inst_epiano(f, hold, vel, sr, p, rng):
    n = int((hold + p.get('release', 0.5)) * sr)
    t = np.arange(n, dtype=np.float32) / sr
    index = 2.2 * vel * np.exp(-t * 3)
    x = np.sin(2 * np.pi * f * t + index * np.sin(2 * np.pi * f * t))
    tine = np.sin(2 * np.pi * f * 14 * t) * np.exp(-t * 30) * 0.15
    return (x + tine) * envelope(n, sr, 0.002, 1.5, 0.3, p.get('release', 0.5), hold) * np.exp(-t * 0.6) * vel * 0.5


def inst_bell(f, hold, vel, sr, p, rng):
    n = int(p.get('length', 4.0) * sr)
    t = np.arange(n, dtype=np.float32) / sr
    index = p.get('index', 4.0) * np.exp(-t * 1.5)
    x = np.sin(2 * np.pi * f * t + index * np.sin(2 * np.pi * f * p.get('ratio', 3.5) * t))
    return x * np.exp(-t * p.get('decay', 1.2)) * vel * 0.45


def inst_pad(f, hold, vel, sr, p, rng):
    """Warm detuned-saw pad with slow attack; `dark` lowers the cutoff."""
    rel = p.get('release', 2.5)
    n = int((hold + rel) * sr)
    x = np.zeros(n, dtype=np.float32)
    for d in (-12, -5, 0, 6, 11):
        x += bl_saw(f * 2 ** (d / 1200), n, sr)
    x = lowpass(x / 5, p.get('cutoff', 1800 if not p.get('dark') else 700), sr, 2)
    return x * envelope(n, sr, p.get('attack', 1.2), 0.5, 0.8, rel, hold) * vel * 0.7


def inst_strings(f, hold, vel, sr, p, rng):
    rel = p.get('release', 0.8)
    n = int((hold + rel) * sr)
    x = np.zeros(n, dtype=np.float32)
    for d, r in ((-7, 5.1), (0, 5.6), (8, 6.0)):
        x += bl_saw(f * 2 ** (d / 1200), n, sr, vibrato=0.08, vib_rate=r)
    x = lowpass(x / 3, p.get('cutoff', 3500), sr, 2)
    return x * envelope(n, sr, p.get('attack', 0.35), 0.3, 0.85, rel, hold) * vel * 0.6


def inst_choir(f, hold, vel, sr, p, rng):
    """Formant choir «aah/ooh»: glottal saw through three vowel formants, gentle vibrato."""
    vowel = VOWELS.get(p.get('vowel', 'a'), VOWELS['a'])
    rel = p.get('release', 1.2)
    n = int((hold + rel) * sr)
    src = np.zeros(n, dtype=np.float32)
    for d in (-6, 0, 7):
        src += bl_saw(f * 2 ** (d / 1200), n, sr, vibrato=0.12, vib_rate=5.2)
    src += rng.normal(0, 0.05, n).astype(np.float32)
    out = sum(bandpass(src, fo, fo / bw, sr) * g for fo, bw, g in vowel)
    return out * envelope(n, sr, p.get('attack', 0.4), 0.3, 0.9, rel, hold) * vel * 0.9


def inst_pluck(f, hold, vel, sr, p, rng):
    """Karplus–Strong string (as an IIR comb, fast in scipy)."""
    n = int(p.get('length', 2.0) * sr)
    N = max(2, int(sr / f))
    g = p.get('sustain', 0.996)
    burst = np.zeros(n, dtype=np.float32)
    burst[:N] = rng.uniform(-1, 1, N)
    a = np.zeros(N + 2)
    a[0] = 1
    a[N] = -g / 2
    a[N + 1] = -g / 2
    y = signal.lfilter([1.0], a, burst).astype(np.float32)
    return lowpass(y, p.get('cutoff', 6000), sr) * vel * 0.5


def inst_bass(f, hold, vel, sr, p, rng):
    rel = p.get('release', 0.25)
    n = int((hold + rel) * sr)
    x = additive([f, f * 2, f / 2], [1, 0.3, 0.5], [0, 0, 0], n, sr) + lowpass(bl_saw(f, n, sr), 600, sr) * 0.4
    return x * envelope(n, sr, 0.005, 0.3, 0.7, rel, hold) * vel * 0.6


def inst_organ(f, hold, vel, sr, p, rng):
    rel = p.get('release', 0.1)
    n = int((hold + rel) * sr)
    x = additive([f / 2, f, f * 2, f * 3, f * 4, f * 6], [0.6, 1, 0.5, 0.3, 0.25, 0.12], [0] * 6, n, sr)
    return x * envelope(n, sr, 0.01, 0.05, 1.0, rel, hold) * vel * 0.3


# Synth drums: fn(sr, vel, params, rng) -> mono. params: pitch (semitones), decay (multiplier).

def _tune(p):
    return 2 ** (float(p.get('pitch', 0)) / 12)


def _dec(p):
    return float(p.get('decay', 1.0))


def drum_kick(sr, vel, p, rng):
    n = int(0.5 * _dec(p) * sr)
    t = np.arange(n) / sr
    f = (45 + 110 * np.exp(-t * 25)) * _tune(p)
    x = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 7 / _dec(p))
    click = highpass(rng.normal(0, 1, n).astype(np.float32), 2000, sr) * np.exp(-t * 300) * 0.3
    return ((x + click) * vel).astype(np.float32)


def drum_kick808(sr, vel, p, rng):
    """Long, boomy 808 kick (sub tail); pitch in semitones retunes the tail (default ~ G1)."""
    n = int(1.4 * _dec(p) * sr)
    t = np.arange(n) / sr
    f = (49 + 90 * np.exp(-t * 30)) * _tune(p)
    x = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 2.2 / _dec(p))
    return (np.tanh(x * 1.6) * vel).astype(np.float32)


def drum_snare(sr, vel, p, rng):
    n = int(0.35 * _dec(p) * sr)
    t = np.arange(n) / sr
    noise = highpass(rng.normal(0, 1, n).astype(np.float32), 1500, sr) * np.exp(-t * 18 / _dec(p))
    body = np.sin(2 * np.pi * 185 * _tune(p) * t) * np.exp(-t * 25)
    return ((noise * 0.6 + body * 0.5) * vel).astype(np.float32)


def drum_clap(sr, vel, p, rng):
    n = int(0.4 * _dec(p) * sr)
    t = np.arange(n) / sr
    noise = bandpass(rng.normal(0, 1, n).astype(np.float32), 1200 * _tune(p), 1.2, sr)
    env = np.zeros(n, np.float32)
    for k, off in enumerate((0, 0.011, 0.022)):
        env += np.where(t >= off, np.exp(-(t - off) * 180), 0) * (0.8 if k < 2 else 1)
    env += np.where(t >= 0.03, np.exp(-(t - 0.03) * 16 / _dec(p)), 0) * 0.6
    return (noise * env * vel * 1.4).astype(np.float32)


def drum_hat(sr, vel, p, rng):
    n = int(0.12 * _dec(p) * sr)
    t = np.arange(n) / sr
    return (highpass(rng.normal(0, 1, n).astype(np.float32), 7000 * _tune(p), sr) * np.exp(-t * 45 / _dec(p)) * vel * 0.5).astype(np.float32)


def _metal(n, sr, base, rng):
    """Six square-ish oscillators at inharmonic ratios (808 cymbal style)."""
    t = np.arange(n) / sr
    return sum(np.sign(np.sin(2 * np.pi * base * r * t + rng.uniform(0, 6))) for r in (1, 1.34, 1.66, 1.9, 2.45, 2.83)) / 6


def drum_ohat(sr, vel, p, rng):
    n = int(0.5 * _dec(p) * sr)
    t = np.arange(n) / sr
    x = highpass((_metal(n, sr, 400 * _tune(p), rng) + rng.normal(0, 0.5, n)).astype(np.float32), 7000, sr)
    return (x * np.exp(-t * 7 / _dec(p)) * vel * 0.45).astype(np.float32)


def drum_crash(sr, vel, p, rng):
    n = int(2.2 * _dec(p) * sr)
    t = np.arange(n) / sr
    x = highpass((_metal(n, sr, 340 * _tune(p), rng) * 0.6 + rng.normal(0, 1, n)).astype(np.float32), 4500, sr)
    return (x * np.exp(-t * 1.8 / _dec(p)) * np.clip(t / 0.003, 0, 1) * vel * 0.4).astype(np.float32)


def drum_ride(sr, vel, p, rng):
    n = int(1.5 * _dec(p) * sr)
    t = np.arange(n) / sr
    ping = additive([3100 * _tune(p), 4870 * _tune(p), 6300 * _tune(p)], [0.5, 0.3, 0.2], [3, 4, 5], n, sr)
    wash = highpass(rng.normal(0, 1, n).astype(np.float32), 6000, sr) * np.exp(-t * 3 / _dec(p)) * 0.3
    return ((ping * 0.5 + wash) * vel * 0.5).astype(np.float32)


def _tom(base):
    def fn(sr, vel, p, rng):
        n = int(0.6 * _dec(p) * sr)
        t = np.arange(n) / sr
        f = base * _tune(p) * (1 + 0.6 * np.exp(-t * 20))
        x = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 6 / _dec(p))
        stick = highpass(rng.normal(0, 1, n).astype(np.float32), 1500, sr) * np.exp(-t * 120) * 0.2
        return ((x + stick) * vel * 0.9).astype(np.float32)
    return fn


def drum_rim(sr, vel, p, rng):
    n = int(0.08 * sr)
    t = np.arange(n) / sr
    x = additive([1700 * _tune(p), 820 * _tune(p)], [0.7, 0.5], [60, 45], n, sr)
    return (x * vel * 0.8 + highpass(rng.normal(0, 1, n).astype(np.float32), 3000, sr) * np.exp(-t * 200) * 0.3 * vel).astype(np.float32)


def drum_shaker(sr, vel, p, rng):
    n = int(0.15 * _dec(p) * sr)
    t = np.arange(n) / sr
    env = np.clip(t / 0.02, 0, 1) * np.exp(-t * 30 / _dec(p))
    return (bandpass(rng.normal(0, 1, n).astype(np.float32), 6500 * _tune(p), 1.5, sr) * env * vel * 0.6).astype(np.float32)


def drum_cowbell(sr, vel, p, rng):
    n = int(0.4 * _dec(p) * sr)
    t = np.arange(n) / sr
    x = np.sign(np.sin(2 * np.pi * 540 * _tune(p) * t)) + np.sign(np.sin(2 * np.pi * 800 * _tune(p) * t))
    return (bandpass(x.astype(np.float32), 800 * _tune(p), 2, sr) * np.exp(-t * 12 / _dec(p)) * vel * 0.5).astype(np.float32)


def drum_snap(sr, vel, p, rng):
    n = int(0.12 * sr)
    t = np.arange(n) / sr
    return (bandpass(rng.normal(0, 1, n).astype(np.float32), 2500 * _tune(p), 3, sr) * np.exp(-t * 60) * vel * 1.2).astype(np.float32)


VOWELS = {  # formant frequency, bandwidth, gain
    'a': [(800, 80, 1.0), (1150, 90, 0.5), (2900, 120, 0.25)],
    'o': [(450, 70, 1.0), (800, 80, 0.4), (2830, 100, 0.15)],
    'u': [(325, 50, 1.0), (700, 60, 0.2), (2530, 170, 0.1)],
    'e': [(400, 60, 1.0), (1700, 80, 0.4), (2600, 120, 0.25)],
    'i': [(270, 60, 1.0), (2140, 90, 0.35), (2950, 100, 0.25)],
}

SYNTHS = {
    'sine': (inst_sine, 'Чистый синус'),
    'saw': (inst_saw, 'Пила с фильтром (cutoff, vibrato)'),
    'square': (inst_square, 'Квадрат (чиптюн)'),
    'triangle': (inst_triangle, 'Треугольник (мягкий чиптюн)'),
    'musicbox': (inst_musicbox, 'Музыкальная шкатулка — колыбельная в духе C418'),
    'piano': (inst_piano, 'Синт-«пианино» (не настоящее; настоящее — instrument "piano")'),
    'epiano': (inst_epiano, 'Электропиано (FM)'),
    'bell': (inst_bell, 'Колокол (FM: ratio, index, decay)'),
    'pad': (inst_pad, 'Тёплый пэд (attack, release, cutoff, dark)'),
    'strings': (inst_strings, 'Струнные (синтез)'),
    'choir': (inst_choir, 'Хор «аа/оо» (vowel: a o u e i)'),
    'pluck': (inst_pluck, 'Щипковая струна (Karplus–Strong)'),
    'bass': (inst_bass, 'Бас'),
    'organ': (inst_organ, 'Орган'),
}
DRUMS = {'kick': drum_kick, 'kick808': drum_kick808, 'snare': drum_snare, 'clap': drum_clap, 'hat': drum_hat,
         'ohat': drum_ohat, 'crash': drum_crash, 'ride': drum_ride, 'tom1': _tom(210), 'tom2': _tom(150),
         'tom3': _tom(105), 'rim': drum_rim, 'shaker': drum_shaker, 'cowbell': drum_cowbell, 'snap': drum_snap}
DRUM_ALIASES = {'bd': 'kick', 'sd': 'snare', 'hh': 'hat', 'chh': 'hat', 'oh': 'ohat', 'ohh': 'ohat', 'tom': 'tom2',
                'tom_high': 'tom1', 'tom_mid': 'tom2', 'tom_low': 'tom3', 'floor': 'tom3', 'sidestick': 'rim',
                '808': 'kick808', 'sub': 'kick808', 'maracas': 'shaker', 'kick2': 'kick', 'snare2': 'snare'}
# Kits: what a drum-grid row name plays. Values: synth drum name | 'gm:<key>' | sample reference.
KITS = {
    'synth': {},                                                       # DRUMS by name, else GM key
    '808': {'kick': 'kick808', 'bd': 'kick808', 'snare': 'clap', 'hat': 'hat', 'ohat': 'ohat'},
    'gm': {'*': 'gm'},                                                 # General MIDI drum kit from the SoundFont
    'mc': {'kick': 'mc:note/bd', 'bd': 'mc:note/bd', 'snare': 'mc:note/snare', 'sd': 'mc:note/snare',
           'clap': 'mc:note/snare', 'hat': 'mc:note/hat', 'hh': 'mc:note/hat', 'ohat': 'mc:note/hat',
           'rim': 'mc:note/hat', 'cowbell': 'mc:note/cow_bell', 'bell': 'mc:note/bell', 'chime': 'mc:note/icechime',
           'xylo': 'mc:note/xylobone', 'bit': 'mc:note/bit', 'pling': 'mc:note/pling', 'bass': 'mc:note/bass'},
}

GM_NAMES = [
    'Acoustic Grand Piano', 'Bright Acoustic Piano', 'Electric Grand Piano', 'Honky-tonk Piano', 'Electric Piano 1',
    'Electric Piano 2', 'Harpsichord', 'Clavinet', 'Celesta', 'Glockenspiel', 'Music Box', 'Vibraphone', 'Marimba',
    'Xylophone', 'Tubular Bells', 'Dulcimer', 'Drawbar Organ', 'Percussive Organ', 'Rock Organ', 'Church Organ',
    'Reed Organ', 'Accordion', 'Harmonica', 'Tango Accordion', 'Nylon Guitar', 'Steel Guitar', 'Jazz Guitar',
    'Clean Guitar', 'Muted Guitar', 'Overdriven Guitar', 'Distortion Guitar', 'Guitar Harmonics', 'Acoustic Bass',
    'Finger Bass', 'Pick Bass', 'Fretless Bass', 'Slap Bass 1', 'Slap Bass 2', 'Synth Bass 1', 'Synth Bass 2',
    'Violin', 'Viola', 'Cello', 'Contrabass', 'Tremolo Strings', 'Pizzicato Strings', 'Orchestral Harp', 'Timpani',
    'String Ensemble 1', 'String Ensemble 2', 'Synth Strings 1', 'Synth Strings 2', 'Choir Aahs', 'Voice Oohs',
    'Synth Voice', 'Orchestra Hit', 'Trumpet', 'Trombone', 'Tuba', 'Muted Trumpet', 'French Horn', 'Brass Section',
    'Synth Brass 1', 'Synth Brass 2', 'Soprano Sax', 'Alto Sax', 'Tenor Sax', 'Baritone Sax', 'Oboe', 'English Horn',
    'Bassoon', 'Clarinet', 'Piccolo', 'Flute', 'Recorder', 'Pan Flute', 'Blown Bottle', 'Shakuhachi', 'Whistle',
    'Ocarina', 'Lead Square', 'Lead Sawtooth', 'Lead Calliope', 'Lead Chiff', 'Lead Charang', 'Lead Voice',
    'Lead Fifths', 'Lead Bass+Lead', 'Pad New Age', 'Pad Warm', 'Pad Polysynth', 'Pad Choir', 'Pad Bowed',
    'Pad Metallic', 'Pad Halo', 'Pad Sweep', 'FX Rain', 'FX Soundtrack', 'FX Crystal', 'FX Atmosphere',
    'FX Brightness', 'FX Goblins', 'FX Echoes', 'FX Sci-fi', 'Sitar', 'Banjo', 'Shamisen', 'Koto', 'Kalimba',
    'Bagpipe', 'Fiddle', 'Shanai', 'Tinkle Bell', 'Agogo', 'Steel Drums', 'Woodblock', 'Taiko Drum', 'Melodic Tom',
    'Synth Drum', 'Reverse Cymbal', 'Guitar Fret Noise', 'Breath Noise', 'Seashore', 'Bird Tweet', 'Telephone Ring',
    'Helicopter', 'Applause', 'Gunshot']


def soundfont_path():
    """Best available SoundFont: a user-added one (any *.sf2 other than the bundled) wins."""
    fonts = sorted(SOUNDFONTS.glob('*.sf2'), key=lambda f: (f.name == 'TimGM6mb.sf2', f.name))
    return fonts[0] if fonts else None


# ----------------------------------------------------------------------------------------------------- SFX generators
# fn(params, sr, rng) -> mono float32.  SFX[name] = (fn, defaults, description)

def sfx_scream(p, sr, rng):
    """Human-like scream: fast pitch attack, strained vibrato, subharmonic «crack» (period doubling), breath noise,
    open-vowel formants and saturation — a hoarse, frightened voice."""
    dur = p['duration']
    n = int(dur * sr)
    t = np.arange(n) / sr
    x01 = t / dur
    base = p['pitch']
    contour = base * (0.7 + 0.6 * p['glide'] * np.clip(t / 0.25, 0, 1)) * (1 - 0.35 * np.clip((x01 - 0.7) / 0.3, 0, 1) ** 2)
    wobble = lowpass(rng.normal(0, 1, n).astype(np.float32), 12, sr) * 8
    f = contour * (1 + 0.035 * np.sin(2 * np.pi * 7.5 * t) + 0.02 * p['rough'] * wobble)
    phase = 2 * np.pi * np.cumsum(f) / sr
    glott = sum(np.sin(k * phase) / k ** 0.8 for k in range(1, 40))
    sub = 1 + p['rough'] * 0.9 * np.sign(np.sin(phase / 2))           # срыв голоса: субгармоника
    src = glott * sub * (1 + 0.3 * p['rough'] * lowpass(rng.normal(0, 1, n).astype(np.float32), 40, sr) * 10)
    breath = rng.normal(0, 1, n) * (0.4 + 0.8 * p['rough'])
    src = (src + breath).astype(np.float32)
    vowel = VOWELS.get(p['vowel'], VOWELS['a'])
    shift = 1.15 + 0.2 * p['glide']                                     # напряжённый голос — форманты выше
    out = sum(bandpass(src, fo * shift, fo / (bw * 3.5), sr) * g * 3 for fo, bw, g in vowel)
    out += highpass(src, 3000, sr) * 0.15
    env = np.clip(t / 0.05, 0, 1) * np.clip((dur - t) / (0.3 * dur), 0, 1) ** 0.6
    out = np.tanh(out * env * (2 + 5 * p['rough']))
    return out.astype(np.float32) * 0.85


def sfx_screech(p, sr, rng):
    """Metal scraping / screeching: noise through drifting resonances + stick–slip grinding + a squeal."""
    n = int(p['duration'] * sr)
    t = np.arange(n) / sr
    noise = rng.normal(0, 1, n).astype(np.float32)
    out = np.zeros(n, dtype=np.float32)
    for _ in range(5):
        f0 = rng.uniform(900, 5200)
        drift = f0 * (1 + 0.15 * np.sin(2 * np.pi * rng.uniform(0.2, 1.5) * t + rng.uniform(0, 6)))
        for i in range(0, n, 2048):   # time-varying resonance, block-wise
            seg = slice(i, min(n, i + 2048))
            out[seg] += bandpass(noise[seg], float(drift[i]), 35, sr) * 0.5
    grind = (rng.uniform(0, 1, n) < p['grit'] * 60 / sr).astype(np.float32)
    grind = np.convolve(grind, np.exp(-np.arange(200) / 30), mode='same')
    out *= 0.4 + 0.6 * np.clip(grind, 0, 1)
    squeal_f = p['squeal'] * (1 + 0.05 * np.sin(2 * np.pi * 3 * t))
    out += 0.25 * np.sin(2 * np.pi * np.cumsum(squeal_f) / sr) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.7 * t))
    env = np.clip(t / 0.05, 0, 1) * np.clip((p['duration'] - t) / 0.3, 0, 1)
    return np.tanh(out * env * 2).astype(np.float32) * 0.7


def sfx_growl(p, sr, rng):
    n = int(p['duration'] * sr)
    t = np.arange(n) / sr
    f = p['pitch'] * (1 + 0.1 * np.sin(2 * np.pi * 0.6 * t)) * (1 + 0.03 * rng.normal(0, 1, n).cumsum() / np.sqrt(n))
    phase = 2 * np.pi * np.cumsum(f) / sr
    src = sum(np.sin(k * phase) / k for k in range(1, 40)) * (0.6 + 0.4 * np.sin(2 * np.pi * p['rattle'] * t))
    src = src + rng.normal(0, 0.3, n)
    out = sum(bandpass(src.astype(np.float32), fo * 0.8, fo / (bw * 3), sr) * g for fo, bw, g in VOWELS['o'])
    env = np.clip(t / 0.3, 0, 1) * np.clip((p['duration'] - t) / 0.6, 0, 1)
    return np.tanh(out * env * 3).astype(np.float32) * 0.7


def sfx_whisper(p, sr, rng):
    """Unintelligible whispering: breathy noise shaped by random vowel formants, syllable by syllable."""
    n = int(p['duration'] * sr)
    noise = highpass(rng.normal(0, 1, n).astype(np.float32), 400, sr)
    out = np.zeros(n, dtype=np.float32)
    pos = 0
    while pos < n:
        syl = int(rng.uniform(0.08, 0.28) / p['rate'] * sr)
        seg = slice(pos, min(n, pos + syl))
        m = seg.stop - seg.start
        vowel = VOWELS[rng.choice(list(VOWELS))]
        part = sum(bandpass(noise[seg], fo * rng.uniform(0.9, 1.3), fo / (bw * 1.5), sr) * g for fo, bw, g in vowel)
        if rng.uniform() < 0.35:   # «с», «ш»
            part = part + highpass(noise[seg], 4500, sr) * 0.6
        out[seg] = part * np.hanning(m) * rng.uniform(0.4, 1)
        pos += syl + int(rng.uniform(0.0, 0.15) * sr)
    return (out * 1.4).astype(np.float32)


def sfx_heartbeat(p, sr, rng):
    beats = int(p['beats'])
    period = 60.0 / p['bpm']
    n = int((beats * period + 0.5) * sr)
    out = np.zeros(n, dtype=np.float32)
    thump_n = int(0.18 * sr)
    tt = np.arange(thump_n) / sr
    thump = np.sin(2 * np.pi * (48 + 30 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 22)
    for b in range(beats):
        for off, g in ((0, 1.0), (0.28 * period, 0.7)):
            i = int((b * period + off) * sr)
            out[i:i + thump_n] += thump[:max(0, min(thump_n, n - i))] * g
    return lowpass(out, 180, sr) * 2.2


def sfx_drone(p, sr, rng):
    """Dark ambient drone: beating low oscillators, slow filter breathing, sub rumble."""
    n = int(p['duration'] * sr)
    t = np.arange(n, dtype=np.float32) / sr
    f = p['pitch']
    out = np.zeros(n, dtype=np.float32)
    for r, d in ((1, 0), (1, 0.7), (1.5, -0.4), (2, 0.3), (0.5, 0)):
        out += bl_saw(f * r + d, n, sr) * (0.6 if r != 0.5 else 1.0)
    lfo = 0.5 + 0.5 * np.sin(2 * np.pi * p['breath'] * t)
    dark = np.zeros(n, dtype=np.float32)
    for i in range(0, n, 4096):
        seg = slice(i, min(n, i + 4096))
        dark[seg] = lowpass(out[seg], 150 + 900 * float(lfo[i]) * p['brightness'], sr)
    rumble = lowpass(rng.normal(0, 1, n).astype(np.float32), 60, sr) * 3
    env = np.clip(t / 2.0, 0, 1) * np.clip((p['duration'] - t) / 2.0, 0, 1)
    return ((dark * 0.35 + rumble * 0.4) * env).astype(np.float32)


def sfx_wind(p, sr, rng):
    n = int(p['duration'] * sr)
    t = np.arange(n) / sr
    noise = rng.normal(0, 1, n).astype(np.float32)
    gust = lowpass(rng.normal(0, 1, n).astype(np.float32), 0.5, sr, 1)
    gust = 0.5 + 0.5 * gust / (np.abs(gust).max() + 1e-6)
    out = np.zeros(n, dtype=np.float32)
    for i in range(0, n, 2048):
        seg = slice(i, min(n, i + 2048))
        out[seg] = bandpass(noise[seg], 300 + 900 * float(gust[i]) * p['howl'], 3 + 6 * p['howl'], sr)
    env = np.clip(t / 1.5, 0, 1) * np.clip((p['duration'] - t) / 1.5, 0, 1)
    return (out * gust * env * 0.8).astype(np.float32)


def sfx_riser(p, sr, rng):
    n = int(p['duration'] * sr)
    t = np.arange(n) / sr
    x = t / p['duration']
    f = p['from_hz'] * (p['to_hz'] / p['from_hz']) ** x
    tone = np.sin(2 * np.pi * np.cumsum(f) / sr) * 0.4
    noise = rng.normal(0, 1, n).astype(np.float32)
    swept = np.zeros(n, dtype=np.float32)
    for i in range(0, n, 2048):
        seg = slice(i, min(n, i + 2048))
        swept[seg] = bandpass(noise[seg], float(f[i]) * 2, 4, sr)
    return ((tone + swept * 0.6) * x ** 2).astype(np.float32)


def sfx_impact(p, sr, rng):
    n = int(p['duration'] * sr)
    t = np.arange(n) / sr
    f = 30 + p['pitch'] * np.exp(-t * 6)
    boom = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-t * 2.5)
    crack = highpass(rng.normal(0, 1, n).astype(np.float32), 1200, sr) * np.exp(-t * 30)
    return np.tanh((boom + crack * 0.5) * 2).astype(np.float32) * 0.8


def sfx_glitch(p, sr, rng):
    n = int(p['duration'] * sr)
    out = np.zeros(n, dtype=np.float32)
    pos = 0
    while pos < n:
        m = int(rng.uniform(0.01, 0.12) * sr)
        kind = rng.integers(0, 4)
        tt = np.arange(m) / sr
        if kind == 0:
            chunk = np.sign(np.sin(2 * np.pi * rng.uniform(80, 2000) * tt))
        elif kind == 1:
            chunk = rng.normal(0, 1, m)
        elif kind == 2:
            chunk = np.sin(2 * np.pi * rng.uniform(2000, 9000) * tt)
        else:
            chunk = np.zeros(m)
        reps = int(rng.integers(1, 4))
        for _ in range(reps):
            e = min(n, pos + m)
            out[pos:e] = chunk[:e - pos] * rng.uniform(0.3, 1)
            pos = e
            if pos >= n:
                break
        pos += int(rng.uniform(0, 0.05) * sr * (1 - p['density']))
    step = int(max(1, 12 * p['crush']))
    out = np.repeat(out[::step], step)[:n]
    return (np.round(out * 6) / 6).astype(np.float32) * 0.6


def sfx_static(p, sr, rng):
    n = int(p['duration'] * sr)
    noise = bandpass(rng.normal(0, 1, n).astype(np.float32), 2500, 0.8, sr)
    crackle = (rng.uniform(0, 1, n) < p['crackle'] * 0.002).astype(np.float32) * rng.uniform(-1, 1, n)
    return (noise * 0.25 + crackle).astype(np.float32)


def sfx_breathing(p, sr, rng):
    period = 60 / p['rate']
    n = int(p['duration'] * sr)
    t = np.arange(n) / sr
    phase = (t % period) / period
    env = np.where(phase < 0.4, np.sin(np.pi * phase / 0.4), np.where(phase < 0.9, 0.7 * np.sin(np.pi * (phase - 0.4) / 0.5), 0))
    noise = rng.normal(0, 1, n).astype(np.float32)
    air = bandpass(noise, 900, 1.2, sr) + bandpass(noise, 2400, 2, sr) * 0.4
    return (air * env * 0.7).astype(np.float32)


def sfx_creak(p, sr, rng):
    """Door / wood creak: stick–slip impulse train (varying rate) exciting wooden resonances."""
    n = int(p['duration'] * sr)
    t = np.arange(n) / sr
    rate = p['rate'] * (1 + 0.6 * np.sin(2 * np.pi * 0.4 * t + rng.uniform(0, 6)))
    ph = np.cumsum(rate) / sr
    imp = (np.diff(np.floor(ph), prepend=0) > 0).astype(np.float32) * rng.uniform(0.5, 1, n)
    out = sum(bandpass(imp, f, 25, sr) * g for f, g in ((p['pitch'], 1), (p['pitch'] * 2.3, 0.5), (p['pitch'] * 4.1, 0.3)))
    env = np.clip(t / 0.1, 0, 1) * np.clip((p['duration'] - t) / 0.2, 0, 1)
    return np.tanh(out * env * 4).astype(np.float32) * 0.8


def sfx_chime(p, sr, rng):
    """Positive sparkle: a cascade of soft bell notes from a pentatonic scale."""
    n = int(p['duration'] * sr)
    out = np.zeros(n, dtype=np.float32)
    scale = [0, 2, 4, 7, 9, 12, 14, 16, 19, 21, 24]
    count = int(p['notes'])
    for i in range(count):
        m = note_to_midi(p['root']) + scale[int(rng.integers(0, len(scale)))]
        at = int((i / max(1, count)) * (p['duration'] - 1.0) * sr * rng.uniform(0.8, 1.0))
        note = inst_bell(midi_to_hz(m), 0.5, rng.uniform(0.3, 0.7), sr, {'length': 2.0, 'ratio': 3.5, 'index': 2.0,
                                                                        'decay': 2.5}, rng)
        e = min(n, at + len(note))
        out[at:e] += note[:e - at]
    return out * 0.7


def sfx_bubbles(p, sr, rng):
    n = int(p['duration'] * sr)
    out = np.zeros(n, dtype=np.float32)
    for _ in range(int(p['count'])):
        at = int(rng.uniform(0, max(0.01, p['duration'] - 0.2)) * sr)
        m = int(0.08 * sr)
        tt = np.arange(m) / sr
        f = rng.uniform(300, 1200) * (1 + 3 * tt / 0.08)
        b = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.exp(-tt * 40)
        e = min(n, at + m)
        out[at:e] += b[:e - at] * rng.uniform(0.2, 0.6)
    return out


def sfx_ufo(p, sr, rng):
    n = int(p['duration'] * sr)
    t = np.arange(n) / sr
    f = p['pitch'] * (1 + 0.25 * np.sin(2 * np.pi * p['warble'] * t))
    x = np.sin(2 * np.pi * np.cumsum(f) / sr) * np.sin(2 * np.pi * 7.3 * t) + 0.3 * np.sin(2 * np.pi * np.cumsum(f * 1.5) / sr)
    env = np.clip(t / 1.0, 0, 1) * np.clip((p['duration'] - t) / 1.0, 0, 1)
    return (x * env * 0.5).astype(np.float32)


def sfx_souls(p, sr, rng):
    """Rising, pleading voices: choir tones gliding upward with breath and whisper."""
    n = int(p['duration'] * sr)
    out = np.zeros(n, dtype=np.float32)
    for i in range(int(p['voices'])):
        start = rng.uniform(0, p['duration'] * 0.4)
        length = p['duration'] - start
        m = int(length * sr)
        base = rng.uniform(180, 420)
        tt = np.arange(m) / sr
        f = base * 2 ** (p['rise'] * tt / length)
        phase = 2 * np.pi * np.cumsum(f * (1 + 0.02 * np.sin(2 * np.pi * 5 * tt))) / sr
        src = sum(np.sin(k * phase) / k for k in range(1, 16)).astype(np.float32)
        voice = sum(bandpass(src, fo, fo / (bw * 2), sr) * g for fo, bw, g in VOWELS[rng.choice(['o', 'u', 'a'])])
        env = np.sin(np.pi * np.clip(tt / length, 0, 1)) ** 1.5
        a = int(start * sr)
        out[a:a + m] += voice * env * 0.5
    return out + sfx_whisper({'duration': p['duration'], 'rate': 0.8}, sr, rng) * 0.25


def sfx_rumble(p, sr, rng):
    n = int(p['duration'] * sr)
    t = np.arange(n) / sr
    base = lowpass(rng.normal(0, 1, n).astype(np.float32), 80, sr, 2) * 6
    cracks = (rng.uniform(0, 1, n) < 8 / sr).astype(np.float32)
    cracks = lowpass(np.convolve(cracks, rng.normal(0, 1, 2000), mode='same'), 600, sr)
    env = np.clip(t / 1.0, 0, 1) * np.clip((p['duration'] - t) / 1.5, 0, 1)
    return np.tanh((base + cracks) * env).astype(np.float32) * 0.9


def sfx_sting(p, sr, rng):
    """Jump-scare stinger: dissonant string cluster + brass stab + impact."""
    n = int(p['duration'] * sr)
    out = np.zeros(n, dtype=np.float32)
    root = note_to_midi(p['root'])
    for iv in (0, 1, 6, 11, 13):
        s = inst_strings(midi_to_hz(root + iv), p['duration'] * 0.6, 0.9, sr, {'attack': 0.01, 'release': 0.6}, rng)
        out[:min(n, len(s))] += s[:n]
    out += np.pad(sfx_impact({'duration': min(p['duration'], 2.5), 'pitch': 90}, sr, rng),
                  (0, max(0, n - int(min(p['duration'], 2.5) * sr))))[:n]
    return np.tanh(out * 1.5).astype(np.float32) * 0.8


SFX = {
    'scream': (sfx_scream, {'duration': 2.0, 'pitch': 480.0, 'glide': 0.5, 'rough': 0.6, 'vowel': 'a'}, 'Крик (человеческий, с хрипом)'),
    'screech': (sfx_screech, {'duration': 2.5, 'grit': 0.6, 'squeal': 3200.0}, 'Скрежет металла / визг'),
    'growl': (sfx_growl, {'duration': 2.5, 'pitch': 70.0, 'rattle': 24.0}, 'Рык монстра'),
    'whisper': (sfx_whisper, {'duration': 4.0, 'rate': 1.0}, 'Неразборчивый шёпот'),
    'heartbeat': (sfx_heartbeat, {'bpm': 70.0, 'beats': 8}, 'Сердцебиение'),
    'drone': (sfx_drone, {'duration': 12.0, 'pitch': 55.0, 'breath': 0.08, 'brightness': 1.0}, 'Тёмный эмбиент-гул'),
    'wind': (sfx_wind, {'duration': 10.0, 'howl': 0.6}, 'Ветер, завывание'),
    'riser': (sfx_riser, {'duration': 4.0, 'from_hz': 80.0, 'to_hz': 1600.0}, 'Нарастание перед событием'),
    'impact': (sfx_impact, {'duration': 3.0, 'pitch': 110.0}, 'Удар / бум'),
    'glitch': (sfx_glitch, {'duration': 1.5, 'density': 0.7, 'crush': 0.5}, 'Цифровой глитч'),
    'static': (sfx_static, {'duration': 3.0, 'crackle': 0.5}, 'Шум радио, треск'),
    'breathing': (sfx_breathing, {'duration': 8.0, 'rate': 14.0}, 'Дыхание'),
    'creak': (sfx_creak, {'duration': 2.0, 'rate': 35.0, 'pitch': 420.0}, 'Скрип двери / дерева'),
    'chime': (sfx_chime, {'duration': 3.0, 'notes': 7, 'root': 'C6'}, 'Искристые колокольчики (позитив)'),
    'bubbles': (sfx_bubbles, {'duration': 2.0, 'count': 14}, 'Пузырьки'),
    'ufo': (sfx_ufo, {'duration': 6.0, 'pitch': 380.0, 'warble': 3.0}, 'Гул НЛО'),
    'souls': (sfx_souls, {'duration': 7.0, 'voices': 5, 'rise': 1.2}, 'Души: голоса улетают вверх'),
    'rumble': (sfx_rumble, {'duration': 5.0}, 'Подземный гул, треск земли'),
    'sting': (sfx_sting, {'duration': 3.0, 'root': 'C3'}, 'Скример-аккорд'),
}


from .horror_sfx import HORROR_SFX, fx_shimmer  # noqa: E402
from .voice_extra import VOICE_SFX, fx_formant  # noqa: E402
SFX.update(HORROR_SFX)
SFX.update(VOICE_SFX)


def _sfx_ai(p, sr, rng):
    from . import neural
    try:
        return neural.sfx_ai(p, sr, rng)
    except neural.NeuralError as exc:
        raise RecipeError(str(exc)) from None


SFX['ai'] = (_sfx_ai, {'prompt': 'distant thunder rumbling', 'duration': 5.0, 'seed': 0, 'model': 'fast'},
             'Нейросеть Woosh: любой звук по описанию (по-английски); model fast|quality')


# ----------------------------------------------------------------------------------------------------- effects

def fx_reverb(x, sr, p, rng):
    size = float(p.get('size', 0.6))
    length = int((0.4 + size * 4.0) * sr)
    t = np.arange(length) / sr
    decay = np.exp(-t / (0.15 + size * 1.2))
    ir = rng.normal(0, 1, (length, 2)).astype(np.float32) * decay[:, None]
    ir = lowpass(ir, 9000 - 6000 * p.get('damping', 0.4), sr)
    pre = int(p.get('predelay', 0.02) * sr)
    ir = np.concatenate([np.zeros((pre, 2), np.float32), ir])
    ir /= np.sqrt((ir ** 2).sum(axis=0, keepdims=True)) + 1e-9
    wet = np.stack([signal.fftconvolve(x[:, c], ir[:, c]) for c in range(2)], axis=1)
    dry = np.pad(x, ((0, len(wet) - len(x)), (0, 0)))
    mix = float(p.get('mix', 0.3))
    return (dry * (1 - mix) + wet * mix * 1.2).astype(np.float32)


def fx_delay(x, sr, p, rng, beat=0.5):
    time = p.get('time', 0.375)
    if isinstance(time, str) and '/' in time:        # «1/4» = четверть такта
        a, b = time.split('/')
        time = beat * 4 * float(a) / float(b)
    d = int(float(time) * sr)
    fb = float(p.get('feedback', 0.4))
    repeats = int(min(30, math.log(0.01) / math.log(max(fb, 1e-3)))) if fb > 0 else 1
    out = np.pad(x, ((0, d * repeats), (0, 0)))
    wet = np.zeros_like(out)
    for k in range(1, repeats + 1):
        g = fb ** (k - 1)
        seg = x * g
        if p.get('pingpong') and k % 2:
            seg = seg[:, ::-1]
        wet[k * d:k * d + len(x)] += seg
    mix = float(p.get('mix', 0.3))
    return (out * (1 - mix * 0.5) + wet * mix).astype(np.float32)


def fx_distortion(x, sr, p, rng):
    drive = float(p.get('drive', 4.0))
    y = np.tanh(x * drive) / np.tanh(drive)
    return (x * (1 - p.get('mix', 1.0)) + y * p.get('mix', 1.0)).astype(np.float32)


def fx_bitcrush(x, sr, p, rng):
    bits = int(p.get('bits', 6))
    down = int(max(1, p.get('downsample', 4)))
    q = 2 ** (bits - 1)
    y = np.round(x * q) / q
    y = np.repeat(y[::down], down, axis=0)[:len(x)]
    return y.astype(np.float32)


def fx_filter(x, sr, p, rng):
    kind = p.get('kind', 'lowpass')
    f = p.get('cutoff', 1000)
    if kind == 'lowpass':
        return lowpass(x, f, sr, int(p.get('order', 2)))
    if kind == 'highpass':
        return highpass(x, f, sr, int(p.get('order', 2)))
    return bandpass(x, f, p.get('q', 2.0), sr)


def fx_pitch(x, sr, p, rng):
    """Tape-style pitch change (speed changes too): semitones."""
    ratio = 2 ** (float(p.get('semitones', -5)) / 12)
    n = int(len(x) / ratio)
    idx = np.arange(n) * ratio
    return np.stack([np.interp(idx, np.arange(len(x)), x[:, c]) for c in range(2)], axis=1).astype(np.float32)


def fx_pitch_shift(x, sr, p, rng):
    """Pitch shift keeping the duration (granular overlap-add, local interpolation per grain)."""
    ratio = 2 ** (float(p.get('semitones', -5)) / 12)
    grain = int(p.get('grain', 0.08) * sr)
    hop = max(1, grain // 4)
    win = np.hanning(grain).astype(np.float32)
    out = np.zeros((len(x) + grain, 2), np.float32)
    norm = np.zeros(len(x) + grain, np.float32)
    k = np.arange(grain) * ratio
    for start in range(0, len(x) - 1, hop):
        idx = start + k
        idx = idx[idx < len(x) - 1]
        if len(idx) < 8:
            break
        i0 = idx.astype(np.int64)
        fr = (idx - i0)[:, None].astype(np.float32)
        g = x[i0] * (1 - fr) + x[i0 + 1] * fr
        m = len(g)
        out[start:start + m] += g * win[:m, None]
        norm[start:start + m] += win[:m]
    return (out / np.maximum(norm, 1e-3)[:, None])[:len(x)].astype(np.float32)


def fx_stretch(x, sr, p, rng):
    """Time-stretch keeping pitch (overlap-add); factor 2 = twice as long."""
    factor = float(p.get('factor', 2.0))
    grain = int(p.get('grain', 0.1) * sr)
    hop_out = grain // 4
    hop_in = hop_out / factor
    win = np.hanning(grain).astype(np.float32)[:, None]
    n_out = int(len(x) * factor) + grain
    out = np.zeros((n_out, 2), np.float32)
    norm = np.zeros((n_out, 1), np.float32)
    pos_in = 0.0
    pos_out = 0
    while pos_in + grain < len(x) and pos_out + grain < n_out:
        s = int(pos_in)
        out[pos_out:pos_out + grain] += x[s:s + grain] * win
        norm[pos_out:pos_out + grain] += win
        pos_in += hop_in
        pos_out += hop_out
    return (out / np.maximum(norm, 1e-3)).astype(np.float32)


def fx_reverse(x, sr, p, rng):
    return x[::-1].copy()


def fx_tremolo(x, sr, p, rng):
    t = np.arange(len(x)) / sr
    lfo = 1 - p.get('depth', 0.6) * (0.5 + 0.5 * np.sin(2 * np.pi * p.get('rate', 6.0) * t))
    return (x * lfo[:, None]).astype(np.float32)


def fx_ringmod(x, sr, p, rng):
    t = np.arange(len(x)) / sr
    carrier = np.sin(2 * np.pi * p.get('freq', 30.0) * t)[:, None]
    mix = p.get('mix', 0.7)
    return (x * (1 - mix) + x * carrier * mix).astype(np.float32)


def fx_chorus(x, sr, p, rng):
    t = np.arange(len(x)) / sr
    out = x.copy()
    for c, ph in ((0, 0.0), (1, 1.7)):
        d = (p.get('delay', 0.02) + p.get('depth', 0.004) * np.sin(2 * np.pi * p.get('rate', 0.8) * t + ph)) * sr
        idx = np.clip(np.arange(len(x)) - d, 0, len(x) - 1)
        out[:, c] = x[:, c] * 0.7 + np.interp(idx, np.arange(len(x)), x[:, c]) * 0.6
    return out.astype(np.float32)


def fx_stutter(x, sr, p, rng, beat=0.5):
    """Beat-synced stutter/glitch: random slices repeat."""
    size = int(beat * sr * p.get('slice', 0.25))
    out = x.copy()
    for start in range(0, len(x) - size, size):
        if rng.uniform() < p.get('amount', 0.3):
            src = out[start:start + size // 2]
            out[start:start + size // 2] = src
            out[start + size // 2:start + size] = src[:size - size // 2]
    return out


def fx_gain(x, sr, p, rng):
    return (x * db(p.get('db', 0.0))).astype(np.float32)


def fx_fade(x, sr, p, rng):
    n = len(x)
    env = np.ones(n, np.float32)
    fi = int(p.get('in', 0) * sr)
    fo = int(p.get('out', 0) * sr)
    if fi:
        env[:fi] *= np.linspace(0, 1, fi)
    if fo:
        env[-fo:] *= np.linspace(1, 0, fo)
    return x * env[:, None]


def fx_compress(x, sr, p, rng):
    thr = db(p.get('threshold', -18))
    ratio = p.get('ratio', 4.0)
    level = np.abs(x).max(axis=1)
    level = signal.lfilter([0.01], [1, -0.99], level)
    gain = np.where(level > thr, (thr + (level - thr) / ratio) / np.maximum(level, 1e-9), 1.0)
    return (x * gain[:, None] * db(p.get('makeup', 3))).astype(np.float32)


def fx_width(x, sr, p, rng):
    mid = (x[:, 0] + x[:, 1]) / 2
    side = (x[:, 0] - x[:, 1]) / 2 * p.get('width', 1.5)
    return np.stack([mid + side, mid - side], axis=1).astype(np.float32)


def fx_eq(x, sr, p, rng):
    """3-band EQ in dB: low shelf, mid peak, high shelf."""
    y = x.copy()
    if p.get('low', 0):
        y += lowpass(x, p.get('low_freq', 200), sr) * (db(p['low']) - 1)
    if p.get('mid', 0):
        y += bandpass(x, p.get('mid_freq', 1000), p.get('mid_q', 1.0), sr) * (db(p['mid']) - 1)
    if p.get('high', 0):
        y += highpass(x, p.get('high_freq', 4000), sr) * (db(p['high']) - 1)
    return y.astype(np.float32)


def fx_sidechain(x, sr, p, rng, beat=0.5):
    """Beat-synced «pumping» (as if ducked by a kick every `every` beats)."""
    t = np.arange(len(x)) / sr
    period = float(p.get('every', 1.0)) * beat
    ph = ((t / period) - float(p.get('offset', 0.0))) % 1.0 * period
    rel = float(p.get('release', 0.3)) * beat
    env = 1 - float(p.get('depth', 0.7)) * np.exp(-ph / max(rel / 4, 1e-3)) * np.clip(ph / 0.002, 0, 1)
    return (x * env[:, None]).astype(np.float32)


def fx_lofi(x, sr, p, rng):
    """Cassette/vinyl vibe: wow & flutter, darker top, hiss, crackle, slight crush."""
    n = len(x)
    t = np.arange(n) / sr
    wow = float(p.get('wow', 0.5))
    d = (0.004 + 0.0025 * wow * np.sin(2 * np.pi * 0.6 * t) + 0.0006 * wow * np.sin(2 * np.pi * 7 * t)) * sr
    idx = np.clip(np.arange(n) - d, 0, n - 1)
    y = np.stack([np.interp(idx, np.arange(n), x[:, c]) for c in range(2)], 1)
    y = lowpass(y, p.get('cutoff', 4500), sr, 2)
    y = highpass(y, 60, sr)
    hiss = highpass(rng.normal(0, 1, (n, 2)).astype(np.float32), 3000, sr) * db(p.get('noise_db', -38))
    crackle = (rng.uniform(0, 1, (n, 1)) < float(p.get('crackle', 0.4)) * 0.0004) * rng.uniform(-0.3, 0.3, (n, 1))
    bits = int(p.get('bits', 12))
    y = np.round(y * 2 ** (bits - 1)) / 2 ** (bits - 1)
    return (y + hiss + crackle).astype(np.float32)


def fx_vibrato(x, sr, p, rng):
    n = len(x)
    t = np.arange(n) / sr
    d = (0.005 + float(p.get('depth', 0.002)) * np.sin(2 * np.pi * float(p.get('rate', 5.5)) * t)) * sr
    idx = np.clip(np.arange(n) - d, 0, n - 1)
    return np.stack([np.interp(idx, np.arange(n), x[:, c]) for c in range(2)], 1).astype(np.float32)


def fx_autopan(x, sr, p, rng, beat=0.5):
    """Pan LFO; rate in Hz or `beats` = one sweep period in beats."""
    t = np.arange(len(x)) / sr
    rate = 1 / (float(p['beats']) * beat) if p.get('beats') else float(p.get('rate', 0.5))
    pan = float(p.get('depth', 0.8)) * np.sin(2 * np.pi * rate * t)
    a = (pan + 1) * math.pi / 4
    mono = x.mean(axis=1)
    return (np.stack([mono * np.cos(a), mono * np.sin(a)], 1) * 1.414).astype(np.float32)


def fx_limiter(x, sr, p, rng):
    thr = db(p.get('threshold', -3))
    peak = np.abs(x).max(axis=1)
    need = np.minimum(1.0, thr / np.maximum(peak, 1e-9))
    rel = 1 - 1 / (float(p.get('release', 0.05)) * sr)
    gain = signal.lfilter([1 - rel], [1, -rel], need)          # smooth
    gain = np.minimum(gain, need)                                 # never exceed the instant need
    return (x * gain[:, None]).astype(np.float32)


def _filter_alias(kind):
    def fn(x, sr, p, rng):
        return fx_filter(x, sr, {**p, 'kind': kind}, rng)
    return fn


EFFECTS = {
    'reverb':(fx_reverb, {'size': 0.6, 'mix': 0.3, 'damping': 0.4, 'predelay': 0.02}, 'Реверберация (зал, пещера)'),
    'delay': (fx_delay, {'time': '1/4', 'feedback': 0.4, 'mix': 0.3, 'pingpong': False}, 'Эхо (время в секундах или долях такта)'),
    'distortion': (fx_distortion, {'drive': 4.0, 'mix': 1.0}, 'Перегруз'),
    'bitcrush': (fx_bitcrush, {'bits': 6, 'downsample': 4}, 'Битовое дробление (ретро/глитч)'),
    'filter': (fx_filter, {'kind': 'lowpass', 'cutoff': 1000, 'q': 2.0, 'order': 2}, 'Фильтр: lowpass/highpass/bandpass'),
    'pitch': (fx_pitch, {'semitones': -5}, 'Высота как на плёнке (меняет скорость)'),
    'pitch_shift': (fx_pitch_shift, {'semitones': -5, 'grain': 0.08}, 'Высота без изменения длины'),
    'stretch': (fx_stretch, {'factor': 2.0, 'grain': 0.1}, 'Растяжение во времени'),
    'reverse': (fx_reverse, {}, 'Задом наперёд'),
    'tremolo': (fx_tremolo, {'rate': 6.0, 'depth': 0.6}, 'Тремоло'),
    'ringmod': (fx_ringmod, {'freq': 30.0, 'mix': 0.7}, 'Кольцевой модулятор (металл, робот)'),
    'chorus': (fx_chorus, {'delay': 0.02, 'depth': 0.004, 'rate': 0.8}, 'Хорус (ширина, «плавание»)'),
    'stutter': (fx_stutter, {'slice': 0.25, 'amount': 0.3}, 'Заикание в ритм'),
    'gain': (fx_gain, {'db': 0.0}, 'Громкость, дБ'),
    'fade': (fx_fade, {'in': 0.0, 'out': 1.0}, 'Плавное появление/затухание, с'),
    'compress': (fx_compress, {'threshold': -18, 'ratio': 4.0, 'makeup': 3}, 'Компрессор'),
    'width': (fx_width, {'width': 1.5}, 'Ширина стерео'),
    'eq': (fx_eq, {'low': 0, 'mid': 0, 'high': 0, 'low_freq': 200, 'mid_freq': 1000, 'mid_q': 1.0, 'high_freq': 4000},
           'Эквалайзер, дБ: low/mid/high'),
    'lowpass': (_filter_alias('lowpass'), {'cutoff': 1000, 'order': 2}, 'Срез верхов'),
    'highpass': (_filter_alias('highpass'), {'cutoff': 200, 'order': 2}, 'Срез низов'),
    'bandpass': (_filter_alias('bandpass'), {'cutoff': 1000, 'q': 2.0}, 'Полоса (телефон, рация)'),
    'sidechain': (fx_sidechain, {'every': 1.0, 'depth': 0.7, 'release': 0.3, 'offset': 0.0},
                  '«Качание» в долю, как под бочку (every в долях)'),
    'lofi': (fx_lofi, {'wow': 0.5, 'cutoff': 4500, 'noise_db': -38, 'crackle': 0.4, 'bits': 12},
             'Лоу-фай: плёнка, шипение, треск'),
    'vibrato': (fx_vibrato, {'rate': 5.5, 'depth': 0.002}, 'Вибрато'),
    'autopan': (fx_autopan, {'rate': 0.5, 'depth': 0.8, 'beats': 0}, 'Панорама качается (rate Гц или beats)'),
    'limiter': (fx_limiter, {'threshold': -3, 'release': 0.05}, 'Лимитер'),
    'shimmer': (fx_shimmer, {'size': 0.9, 'mix': 0.45, 'amount': 0.6, 'semitones': 12},
                'Шиммер: реверб с октавой вверх — «ангельский» ореол'),
    'formant': (fx_formant, {'shift': 1.2, 'pitch_semitones': 0, 'mix': 1.0, 'monotone': 0},
                'Сдвиг формант голоса (меньше/больше существо), pitch_semitones, monotone Гц'),
}
BEAT_SYNCED = {'delay', 'stutter', 'sidechain', 'autopan'}


def apply_effects(x, sr, effects, rng, beat=0.5, log=None):
    for e in effects or []:
        kind = e.get('type')
        if kind not in EFFECTS:
            raise RecipeError(f'нет эффекта {kind!r}; есть: {", ".join(EFFECTS)}')
        fn, defaults, _ = EFFECTS[kind]
        params = {**defaults, **{k: v for k, v in e.items() if k != 'type'}}
        if log:
            log(f'  эффект {kind} {json.dumps({k: v for k, v in e.items() if k != "type"}, ensure_ascii=False)}')
        if kind in BEAT_SYNCED:
            x = fn(x, sr, params, rng, beat=beat)
        else:
            x = fn(x, sr, params, rng)
    return x


# ----------------------------------------------------------------------------------------------------- rendering

def curve(points, beats, default):
    """Linear automation curve [[beat, value], ...] evaluated at beat positions."""
    if not points:
        return np.full(np.shape(beats), default, dtype=np.float32)
    pts = sorted(points, key=lambda p: p[0])
    return np.interp(beats, [p[0] for p in pts], [p[1] for p in pts]).astype(np.float32)


def load_audio(source, sr, library_dir):
    """Any sample reference (mc:, samples:, library:, path) → stereo float32 at sr."""
    from . import samples
    try:
        return samples.load(source, sr, library_dir)
    except samples.SampleError as exc:
        raise RecipeError(str(exc)) from None


def _resample(x, ratio):
    """Play `x` (mono or stereo) `ratio` times faster, tape-style."""
    n = int(len(x) / ratio)
    if n < 2:
        return np.zeros((2,) + x.shape[1:], np.float32)
    idx = np.arange(n) * ratio
    if x.ndim == 1:
        return np.interp(idx, np.arange(len(x)), x).astype(np.float32)
    return np.stack([np.interp(idx, np.arange(len(x)), x[:, c]) for c in range(x.shape[1])], 1).astype(np.float32)


def sampler_note(data, midi, hold, vel, sr, p):
    """Pitched playback of a mono sample. p: root, gate, loop, attack, release, start (s), gain."""
    root = note_to_midi(p.get('root', 'C4'))
    ratio = 2 ** ((midi - root) / 12)
    src = data[int(float(p.get('start', 0)) * sr):]
    release = float(p.get('release', 0.08))
    loop = bool(p.get('loop'))
    if loop and len(src) / ratio < (hold + release) * sr:
        src = np.tile(src, int(math.ceil((hold + release) * sr * ratio / max(len(src), 1))) + 1)
    y = _resample(src, ratio)
    if p.get('gate', loop):
        n = min(len(y), int((hold + release) * sr))
        t = np.arange(n) / sr
        y = y[:n] * np.where(t > hold, np.exp(-(t - hold) / max(release, 1e-3) * 4.6), 1.0).astype(np.float32)
    att = min(len(y), int(float(p.get('attack', 0.002)) * sr))
    if att > 1:
        y = y.copy()
        y[:att] *= np.linspace(0, 1, att, dtype=np.float32)
    return y * vel * float(p.get('gain', 1.0))


def render_notes_synth(track, sr, beat, rng, log, library_dir=None):
    inst = track.get('instrument', {'synth': 'piano'})
    params = inst.get('params', {})
    auto = track.get('automation', {})
    pieces = []
    cache = {}
    data = None
    if 'sample' in inst:
        data = load_audio(inst['sample'], sr, library_dir).mean(axis=1)
        params = {k: v for k, v in inst.items() if k not in ('sample', 'params')} | params
        if str(params.get('root', '')).lower() == 'auto':
            from .analysis import estimate_pitch
            hz, _ = estimate_pitch(data, sr)
            params['root'] = 69 + 12 * math.log2(hz / 440) if hz else 60
            log(f'  высота сэмпла: {params["root"]:.2f} (MIDI)')
    for note in track.get('notes', []):
        start, length = float(note[0]), float(note[1])
        vel = float(note[3]) if len(note) > 3 else 0.8
        opts = note[4] if len(note) > 4 and isinstance(note[4], dict) else {}
        if 'drum' in inst:
            kind = note[2] if isinstance(note[2], str) and note[2] in DRUMS else inst['drum']
            audio = DRUMS[kind](sr, vel, {**params, **opts}, rng)
        else:
            m = note_to_midi(note[2]) + float(curve(auto.get('detune'), [start], 0.0)[0]) / 100.0 + float(opts.get('pitch', 0))
            key = (round(m, 3), round(length * beat, 4), round(vel, 3))      # loops repeat notes: render once
            if key in cache:
                audio = cache[key]
            elif data is not None:
                audio = cache[key] = sampler_note(data, m, length * beat, vel, sr, params)
            else:
                audio = cache[key] = SYNTHS[inst['synth']][0](midi_to_hz(m), length * beat, vel, sr, params, rng)
        if opts.get('gain'):
            audio = audio * float(opts['gain'])
        pieces.append((int(start * beat * sr), audio))
    return pieces


def kit_voice(kit, row, depth=0):
    """Drum-grid row → ('synth', name) | ('gm', key) | ('sample', ref)."""
    from .notation import GM_DRUM_KEYS
    if isinstance(row, (int, float)) or str(row).isdigit():
        return 'gm', int(row)
    row = str(row)
    if row.startswith(('mc:', 'samples:', 'library:')) or '/' in row or '\\' in row:
        return 'sample', row
    if row.startswith('gm:'):
        name = row[3:]
        return 'gm', int(name) if name.isdigit() else GM_DRUM_KEYS[name]
    mapping = kit if isinstance(kit, dict) else KITS.get(kit)
    if mapping is None:
        raise RecipeError(f'нет набора ударных {kit!r}; есть: {", ".join(KITS)} или словарь {{строка: звук}}')
    value = mapping.get(row, mapping.get('*'))
    if value == 'gm':
        if row in GM_DRUM_KEYS:
            return 'gm', GM_DRUM_KEYS[row]
        value = None
    if value is not None and value != row and depth < 4:
        return kit_voice('synth', value, depth + 1)
    name = DRUM_ALIASES.get(row, row)
    if name in DRUMS:
        return 'synth', name
    if row in GM_DRUM_KEYS:
        return 'gm', GM_DRUM_KEYS[row]
    raise RecipeError(f'не знаю удар {row!r}: {", ".join(DRUMS)}, GM: {", ".join(GM_DRUM_KEYS)}, или ссылка на сэмпл mc:/samples:')


def render_kit(track, sr, beat, rng, log, library_dir=None):
    """Drum track: every note's pitch field is a row name (kick, snare, mc:note/bd, gm:ride, …)."""
    inst = track['instrument']
    kit = inst.get('kit', 'synth')
    params = inst.get('params', {})
    pieces, gm_notes, cache = [], [], {}
    for note in track.get('notes', []):
        start, length = float(note[0]), float(note[1])
        vel = float(note[3]) if len(note) > 3 else 0.8
        opts = note[4] if len(note) > 4 and isinstance(note[4], dict) else {}
        row = note[2]
        if row not in cache:
            cache[row] = kit_voice(kit, row)
        kind, v = cache[row]
        vel *= float(opts.get('gain', 1.0))
        if kind == 'gm':
            gm_notes.append([start, max(length, 0.25), v, min(1.0, vel)])
            continue
        if kind == 'synth':
            audio = DRUMS[v](sr, vel, {**params, **opts}, rng)
        else:
            key = ('data', v)
            if key not in cache:
                cache[key] = load_audio(v, sr, library_dir).mean(axis=1)
            audio = sampler_note(cache[key], 60 + float(opts.get('pitch', params.get('pitch', 0))), length * beat, vel, sr,
                                 {'root': 60, 'gate': bool(opts.get('gate', False)), 'release': 0.05})
        pieces.append((int(start * beat * sr), audio))
    end = max((s + len(a) for s, a in pieces), default=1)
    mono = np.zeros(end, np.float32)
    for s, a in pieces:
        mono[s:s + len(a)] += a
    audio = stereo(mono)
    if gm_notes:
        log(f'  GM ударные: {len(gm_notes)} ударов')
        g = render_notes_gm({'instrument': {'gm_drums': True}, 'notes': gm_notes}, sr, beat, log)
        if len(g) > len(audio):
            audio = np.pad(audio, ((0, len(g) - len(audio)), (0, 0)))
        audio[:len(g)] += g
    return audio


def render_notes_gm(track, sr, beat, log):
    import tinysoundfont
    from .notation import GM_DRUM_KEYS
    sf_path = soundfont_path()
    if not sf_path:
        raise RecipeError('нет SoundFont (*.sf2) в soundlab/soundfonts')
    inst = track['instrument']
    synth = tinysoundfont.Synth(samplerate=sr)
    sfid = synth.sfload(str(sf_path))
    drums = bool(inst.get('gm_drums'))
    chan = 9 if drums else 0
    synth.program_select(chan, sfid, 128 if drums else int(inst.get('bank', 0)), 0 if drums else int(inst['gm']), is_drums=drums)
    auto = track.get('automation', {})
    events = []
    for note in track.get('notes', []):
        start, length = float(note[0]), float(note[1])
        vel = int(np.clip((float(note[3]) if len(note) > 3 else 0.8) * 127, 1, 127))
        key = GM_DRUM_KEYS[note[2]] if isinstance(note[2], str) and note[2] in GM_DRUM_KEYS else int(round(note_to_midi(note[2])))
        bend = float(curve(auto.get('detune'), [start], 0.0)[0])      # центы → pitch bend (±2 полутона)
        events.append((start * beat, 1, key, vel, bend))
        events.append(((start + length) * beat, 0, key, 0, 0))
    events.sort(key=lambda e: (e[0], e[1]))
    total = (events[-1][0] if events else 0) + 4.0
    chunks = []
    now = 0.0
    for when, on, key, vel, bend in events:
        n = int((when - now) * sr)
        if n > 0:
            chunks.append(np.frombuffer(synth.generate(n), dtype=np.float32).reshape(-1, 2).copy())
            now += n / sr
        if on:
            if not drums:
                synth.pitchbend(chan, int(np.clip(8192 + bend / 200.0 * 8192, 0, 16383)))
            synth.noteon(chan, key, vel)
        else:
            synth.noteoff(chan, key)
    tail = int((total - now) * sr)
    if tail > 0:
        chunks.append(np.frombuffer(synth.generate(tail), dtype=np.float32).reshape(-1, 2).copy())
    audio = np.concatenate(chunks) if chunks else np.zeros((1, 2), np.float32)
    return audio * 1.6


SEQ_RE = re.compile(r'^(?:(\d+)(r?)|([._-]))(?::([\d./]+))?$')


def chop(audio, track, sr, beat):
    """Remix: cut audio into `slices` equal parts and replay them in `sequence` order ("0 1 2 3 . 2r 3:2")."""
    k = max(1, int(track['slices']))
    size = len(audio) // k
    parts = [audio[i * size:(i + 1) * size] for i in range(k)]
    step = float(track.get('step', size / sr / beat))
    step_n = int(step * beat * sr)
    seq = str(track.get('sequence', ' '.join(map(str, range(k))))).split()
    placed, t = [], 0
    for tok in seq:
        if set(tok) <= set('|'):
            continue
        m = SEQ_RE.match(tok)
        if not m:
            raise RecipeError(f'sequence: не понимаю {tok!r} (номер среза, r — задом наперёд, :2 — длина в шагах, . — пауза)')
        steps = float(eval_fraction(m.group(4))) if m.group(4) else 1.0
        if m.group(1) is not None:
            seg = parts[int(m.group(1)) % k]
            if m.group(2):
                seg = seg[::-1]
            seg = seg[:int(steps * step_n)].copy()
            fade = min(len(seg), int(0.004 * sr))
            if fade > 1:
                seg[-fade:] *= np.linspace(1, 0, fade, dtype=np.float32)[:, None]
            placed.append((t, seg))
        t += int(steps * step_n)
    out = np.zeros((max(t, max((s + len(g) for s, g in placed), default=1)), 2), np.float32)
    for s, g in placed:
        out[s:s + len(g)] += g
    return out


def eval_fraction(text):
    if '/' in text:
        a, b = text.split('/', 1)
        return float(a or 1) / float(b)
    return float(text)


def _apply_span(recipe, span):
    """Keep only beats [a, b) of an expanded recipe and shift them to 0 (fast previews)."""
    a, b = float(span[0]), float(span[1])
    tracks = []
    for tr in recipe['tracks']:
        tr = dict(tr)
        if tr.get('type', 'notes') == 'notes':
            tr['notes'] = [[n[0] - a] + list(n[1:]) for n in tr.get('notes', []) if a - 1e-6 <= n[0] < b]
        else:
            at = float(tr.get('at', 0))
            if at >= b:
                continue
            tr['at'] = at - a
        if tr.get('automation'):
            tr['automation'] = {k: [[p[0] - a, p[1]] for p in pts] for k, pts in tr['automation'].items()}
        tracks.append(tr)
    recipe['tracks'] = tracks
    master = dict(recipe.get('master', {}))
    master['length_beats'] = b - a
    master.setdefault('fade_out', 0.3)
    recipe['master'] = master
    return recipe


def render(recipe, library_dir=None, log=None, span=None):
    """Render a recipe (compact or explicit). span=(from_beat, to_beat) renders only that part.
    Returns (stereo float32 array, sample rate, report dict)."""
    from . import notation
    log = log or (lambda msg: None)
    if not isinstance(recipe, dict):
        raise RecipeError('рецепт должен быть объектом JSON')
    try:
        recipe = notation.expand_recipe(recipe)
    except (notation.NotationError, KeyError) as exc:
        raise RecipeError(str(exc)) from None
    if span:
        recipe = _apply_span(recipe, span)
        log(f'предпросмотр долей {span[0]}–{span[1]}')
    sr = int(recipe.get('sample_rate', 44100))
    tempo = float(recipe.get('tempo', 90))
    beat = 60.0 / tempo
    tracks = recipe.get('tracks', [])
    if not tracks:
        raise RecipeError('в рецепте нет дорожек (tracks)')
    rendered = []
    for ti, track in enumerate(tracks):
        kind = track.get('type', 'notes')
        name = track.get('name', f'track{ti + 1}')
        if track.get('mute'):
            continue
        if any(t.get('solo') for t in tracks) and not track.get('solo'):
            continue
        rng = rng_for(recipe.get('seed', 0), ti, name)
        log(f'дорожка {ti + 1}/{len(tracks)} «{name}» ({kind})')
        offset = 0
        if kind == 'notes':
            inst = track.get('instrument', {'synth': 'piano'})
            if not track.get('notes'):
                continue
            detune_fn = (lambda b, pts=track.get('automation', {}).get('detune'): float(curve(pts, [b], 0.0)[0])) \
                if track.get('automation', {}).get('detune') else None
            if 'sfz' in inst:
                from . import sfz
                try:
                    audio = sfz.render_track(track, sr, beat, log, detune_fn)
                except sfz.SfzError as exc:
                    raise RecipeError(str(exc)) from None
            elif 'singer' in inst:
                from . import neural
                try:
                    audio = neural.render_singer_track(track, sr, beat, log, detune_fn)
                except neural.NeuralError as exc:
                    raise RecipeError(str(exc)) from None
            elif 'voice' in inst:
                from . import voice
                try:
                    audio = voice.render_track(track, sr, beat, log, detune_fn)
                except voice.VoiceError as exc:
                    raise RecipeError(str(exc)) from None
            elif 'kit' in inst:
                log(f'  ударные, набор {inst["kit"] if isinstance(inst["kit"], str) else "свой"}, ударов: {len(track["notes"])}')
                audio = render_kit(track, sr, beat, rng, log, library_dir)
            elif 'gm' in inst or inst.get('gm_drums'):
                label = 'GM ударные' if inst.get('gm_drums') else f'GM {inst["gm"]} {GM_NAMES[int(inst["gm"]) % 128]}'
                log(f'  инструмент: {label} из SoundFont {soundfont_path().name if soundfont_path() else "—"}, нот: {len(track.get("notes", []))}')
                audio = render_notes_gm(track, sr, beat, log)
            else:
                if 'synth' in inst and inst['synth'] not in SYNTHS:
                    raise RecipeError(f'нет синтезатора {inst["synth"]!r}; есть: {", ".join(SYNTHS)}')
                label = inst.get('synth') or inst.get('drum') or f'сэмпл {inst.get("sample")}'
                log(f'  {label}, нот: {len(track.get("notes", []))}')
                pieces = render_notes_synth(track, sr, beat, rng, log, library_dir)
                end = max((s + len(a) for s, a in pieces), default=1)
                mono = np.zeros(end, np.float32)
                for s, a in pieces:
                    mono[s:s + len(a)] += a
                audio = stereo(mono)
        elif kind == 'sfx':
            name_sfx = track.get('sfx')
            if name_sfx not in SFX:
                raise RecipeError(f'нет генератора {name_sfx!r}; есть: {", ".join(SFX)}')
            fn, defaults, _ = SFX[name_sfx]
            params = {**defaults, **track.get('params', {})}
            if 'duration_beats' in track:
                params['duration'] = float(track['duration_beats']) * beat
            log(f'  генератор {name_sfx} {json.dumps(track.get("params", {}), ensure_ascii=False)}')
            one = stereo(fn(params, sr, rng))
            rep = track.get('repeat', {})
            count = int(rep.get('count', 1))
            every = float(rep.get('every', 0)) * beat
            length = int((every * (count - 1)) * sr) + len(one)
            audio = np.zeros((length, 2), np.float32)
            for k in range(count):
                s = int(k * every * sr)
                audio[s:s + len(one)] += one
            offset = int(float(track.get('at', 0)) * beat * sr)
        elif kind == 'audio':
            audio = load_audio(track['source'], sr, library_dir or HERE / 'library')
            if track.get('trim'):
                a, b = track['trim']
                audio = audio[int(a * sr):int(b * sr) if b else None]
            if track.get('rate'):
                audio = _resample(audio, float(track['rate']))
            if track.get('semitones'):
                audio = fx_pitch_shift(audio, sr, {'semitones': float(track['semitones']), 'grain': 0.08}, rng)
            if track.get('fit_beats'):
                want = int(float(track['fit_beats']) * beat * sr)
                audio = fx_stretch(audio, sr, {'factor': want / max(len(audio), 1), 'grain': 0.06}, rng)[:want]
            if track.get('reverse'):
                audio = audio[::-1].copy()
            if track.get('slices'):
                audio = chop(audio, track, sr, beat)
            loops = int(track.get('loop', 1))
            audio = np.concatenate([audio] * max(1, loops))
            offset = int(float(track.get('at', 0)) * beat * sr)
            log(f'  аудио {track["source"]} ×{loops}' + (f', {track["slices"]} срезов' if track.get('slices') else ''))
        else:
            raise RecipeError(f'неизвестный тип дорожки {kind!r} (notes / sfx / audio)')
        audio = apply_effects(audio, sr, track.get('effects'), rng, beat, log)
        rendered.append((offset, audio, track))
    if not rendered:
        raise RecipeError('нечего играть: все дорожки пустые или выключены')
    total = max(max(o, 0) + len(a) + min(o, 0) for o, a, _ in rendered)
    mix = np.zeros((max(total, 1), 2), np.float32)
    for offset, audio, track in rendered:
        n = len(audio)
        beats = (offset + np.arange(n)) / sr / beat
        auto = track.get('automation', {})
        gain = float(track.get('gain', 0.8)) * curve(auto.get('gain'), beats, 1.0)
        if auto.get('lowpass'):
            cut = curve(auto['lowpass'], beats, 20000)
            out = np.empty_like(audio)
            for i in range(0, n, 2048):
                seg = slice(i, min(n, i + 2048))
                b, a = signal.butter(2, float(np.clip(cut[i], 40, sr * 0.45)) / (sr / 2), 'low')
                out[seg] = signal.lfilter(b, a, audio[seg], axis=0)
            audio = out
        pan = curve(auto.get('pan'), beats, float(track.get('pan', 0.0)))
        mono_l, mono_r = audio[:, 0], audio[:, 1]
        a = (np.clip(pan, -1, 1) + 1) * math.pi / 4
        audio = np.stack([mono_l * np.cos(a) * 1.414, mono_r * np.sin(a) * 1.414], axis=1) * gain[:, None]
        if offset < 0:
            audio, offset = audio[-offset:], 0
        mix[offset:offset + len(audio)] += audio[:max(0, len(mix) - offset)]
    master = recipe.get('master', {})
    rng = rng_for(recipe.get('seed', 0), 'master')
    if master.get('effects'):
        log('мастер-эффекты')
    mix = apply_effects(mix, sr, master.get('effects'), rng, beat, log)
    if master.get('length_beats'):
        mix = mix[:int(float(master['length_beats']) * beat * sr) + int(float(master.get('tail', 0)) * sr)]
    if master.get('trim', True):                                   # срезать тишину в конце
        loud = np.nonzero(np.abs(mix).max(axis=1) > db(-60) * max(float(np.abs(mix).max()), 1e-9))[0]
        if len(loud):
            mix = mix[:loud[-1] + int(0.02 * sr)]
    if master.get('fade_out'):
        mix = fx_fade(mix, sr, {'out': min(float(master['fade_out']), len(mix) / sr)}, rng)
    peak = float(np.abs(mix).max()) or 1.0
    target = db(float(master.get('normalize', -1.0)))
    mix = mix * (target / peak)
    mix = np.tanh(mix * 1.05) / np.tanh(1.05)                      # мягкий лимитер
    if int(recipe.get('channels', 2)) == 1:
        mix = np.repeat(mix.mean(axis=1, keepdims=True), 2, axis=1)
    report = {'seconds': round(len(mix) / sr, 2), 'tracks': len(rendered), 'peak_before_db': round(20 * math.log10(peak), 1),
              'tempo': tempo, 'beats': round(len(mix) / sr / beat, 2)}
    if recipe.get('_sections'):
        report['sections'] = recipe['_sections']
    log(f'готово: {report["seconds"]} с, дорожек {report["tracks"]}')
    return mix.astype(np.float32), sr, report


def catalog(section='all'):
    """Everything the recipes can use. section: all | synths | gm | drums | sfx | effects | notation | samples."""
    from . import notation, samples
    full = {
        'synths': {k: v[1] for k, v in SYNTHS.items()},
        'gm': GM_NAMES,
        'gm_aliases': {k: v for k, v in sorted(notation.ALIAS_TO_GM.items(), key=lambda kv: kv[1])},
        'soundfont': soundfont_path().name if soundfont_path() else None,
        'drums': {'synth_drums': list(DRUMS), 'aliases': DRUM_ALIASES, 'kits': {k: v for k, v in KITS.items()},
                  'gm_drum_keys': notation.GM_DRUM_KEYS},
        'noteblock': {k: v for k, v in samples.NOTE_BLOCK_ROOTS.items()},
        'sfx': {k: {'defaults': v[1], 'description': v[2]} for k, v in SFX.items()},
        'effects': {k: {'defaults': v[1], 'description': v[2]} for k, v in EFFECTS.items()},
        'notation': {'chord_qualities': list(notation.CHORD_QUALITIES), 'modes': list(notation.MODES),
                     'chord_styles': ['block', 'pulse', 'strum', 'arp', 'arp_down', 'arp_updown', 'alberti', 'root',
                                      'root_fifth', 'root_octave'],
                     'grid_chars': 'x=0.85 X=1 o=0.55 O=0.7 g=0.3 r=ролл×2 R t=ролл×3 1-9=громкость . - _ пауза'},
        'samples': samples.stats(),
        'real': _real_catalog(),
    }
    if section == 'all':
        return full
    if section == 'instruments':
        return {k: full[k] for k in ('real', 'synths', 'gm', 'gm_aliases', 'noteblock', 'soundfont')}
    if section not in full:
        raise RecipeError(f'нет раздела {section!r}: {", ".join(full)}, instruments')
    return {section: full[section]}


def _real_catalog():
    """Live recorded instruments (SFZ libraries) and singing voices."""
    from . import sfz, voice
    items = sfz.all_sfz()
    return {'presets': sfz.installed_presets(), 'aliases_ru': sfz.REAL_ALIASES, 'sfz_installed': len(items),
            'sfz_names_example': sorted(items)[:40], 'voices': list(voice.VOICES),
            'voice_presets': {'voice': 'соло-голос', 'choir voices': 'хор из голосов, поёт слова (lyrics)'}}
