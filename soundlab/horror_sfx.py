"""Horror SFX generators: claws/nails scraping walls, something crawling, air-raid siren (Siren Head), plus the
shimmer reverb for angelic choirs. Signature like engine SFX: fn(params, sr, rng) -> mono float32."""
import numpy as np
from scipy import signal


def _lp(x, f, sr, order=2):
    b, a = signal.butter(order, min(f, sr * 0.45) / (sr / 2), 'low')
    return signal.lfilter(b, a, x).astype(np.float32)


def _hp(x, f, sr, order=2):
    b, a = signal.butter(order, max(f, 10) / (sr / 2), 'high')
    return signal.lfilter(b, a, x).astype(np.float32)


def _bp(x, f, q, sr):
    b, a = signal.iirpeak(min(max(f, 30), sr * 0.45) / (sr / 2), max(q, 0.3))
    return signal.lfilter(b, a, x).astype(np.float32)


def _strokes(dur, sr, rng, rate, min_len=0.35, max_len=1.4):
    """Hand/claw motion: bumps of velocity 0..1 with pauses. rate = strokes per second."""
    n = int(dur * sr)
    v = np.zeros(n, np.float32)
    t = rng.uniform(0, 0.2)
    while t < dur - 0.1:
        ln = rng.uniform(min_len, max_len)
        s, e = int(t * sr), min(n, int((t + ln) * sr))
        if e > s:
            x = np.linspace(0, 1, e - s)
            v[s:e] = np.maximum(v[s:e], (np.sin(np.pi * x) ** 0.7) * rng.uniform(0.6, 1.0))
        t += ln + rng.uniform(0.05, 1.2) / max(rate, 0.05)
    return v


MATERIALS = {   # resonances (Hz, q, gain), grain rate at full speed, top cutoff, squeal range
    'stone': ([(900, 3, 1.0), (1700, 4, 0.8), (2600, 5, 0.5)], 700, 6000, None),
    'wood': ([(420, 6, 1.0), (980, 8, 0.7), (1850, 8, 0.4)], 260, 4500, (300, 700)),
    'metal': ([(2300, 25, 1.0), (3900, 30, 0.8), (6100, 30, 0.5)], 900, 11000, (1800, 4200)),
    'nails': ([(2800, 6, 1.0), (4400, 7, 0.9), (6800, 8, 0.5)], 1400, 12000, (2500, 5200)),
    'glass': ([(3200, 20, 1.0), (5200, 25, 0.9), (7600, 25, 0.6)], 1100, 13000, (2800, 6000)),
}


def sfx_scrape(p, sr, rng):
    """Scraping along a wall: claws on stone, nails on a door, metal on metal. Stick–slip friction driven by hand
    motion, material resonances, optional squeal."""
    res, grain_rate, top, squeal = MATERIALS.get(p['material'], MATERIALS['stone'])
    n = int(p['duration'] * sr)
    v = _strokes(p['duration'], sr, rng, p['speed'])
    noise = rng.normal(0, 1, n).astype(np.float32)
    # stick-slip: impulses with rate ~ velocity
    ph = np.cumsum(grain_rate * (0.2 + v) * rng.uniform(0.7, 1.3, n)) / sr
    imp = (np.diff(np.floor(ph), prepend=0) > 0).astype(np.float32) * rng.uniform(0.3, 1, n)
    src = noise * (0.25 + 0.75 * p['pressure']) * 0.4 + imp * (1.5 + 2 * p['pressure'])
    out = sum(_bp(src, f * rng.uniform(0.95, 1.05), q, sr) * g for f, q, g in res)
    out += _hp(noise, 3000, sr) * 0.15 * p['grit']
    for k in range(int(p['claws']) - 1):                                 # several claws = offset copies
        d = int(rng.uniform(0.004, 0.02) * sr)
        out[d:] += out[:-d] * 0.6
    out = _lp(out, top, sr) * v
    if squeal and p['squeal'] > 0:
        t = np.arange(n) / sr
        f = rng.uniform(*squeal) * (1 + 0.08 * np.sin(2 * np.pi * rng.uniform(1, 4) * t)) * (0.85 + 0.3 * v)
        sq = np.sin(2 * np.pi * np.cumsum(f) / sr) * (v > 0.5) * (v - 0.5) * 2
        out += (sq * p['squeal'] * 0.5).astype(np.float32)
    return np.tanh(out * 1.5).astype(np.float32) * 0.8


def sfx_crawl(p, sr, rng):
    """Something crawling: uneven limb impacts, scratches, a dragged body, optional wet flesh and bone cracks."""
    n = int(p['duration'] * sr)
    out = np.zeros(n, np.float32)
    limbs = int(p['limbs'])
    t = rng.uniform(0, 0.3)
    drag = np.zeros(n, np.float32)
    while t < p['duration'] - 0.3:
        group = rng.permutation(limbs)[:max(1, limbs // 2)]
        for i, _ in enumerate(group):
            s = int((t + i * rng.uniform(0.03, 0.12)) * sr)
            if s >= n:
                break
            m = int(0.25 * sr)
            tt = np.arange(m) / sr
            thud = np.sin(2 * np.pi * (70 + 60 * np.exp(-tt * 40)) * tt) * np.exp(-tt * 25) * p['weight']
            tap = _hp(rng.normal(0, 1, m).astype(np.float32), 1500, sr) * np.exp(-tt * 90) * (1 - p['weight'] * 0.5)
            scr_len = int(rng.uniform(0.05, 0.18) * sr)
            scr = np.zeros(m, np.float32)
            scr[:scr_len] = _bp(rng.normal(0, 1, scr_len).astype(np.float32), rng.uniform(1500, 3500), 2, sr) * np.hanning(scr_len)
            hit = (thud + tap * 0.6 + scr * 0.5 * p['claws']) * rng.uniform(0.5, 1.0)
            if p['bones'] > 0 and rng.uniform() < p['bones'] * 0.4:            # bone / joint crack
                c = np.zeros(m, np.float32)
                for _ in range(int(rng.integers(2, 6))):
                    k = int(rng.uniform(0, 0.08) * sr)
                    c[k:k + 60] += rng.normal(0, 1, 60).astype(np.float32) * np.exp(-np.arange(60) / 8)
                hit += _bp(c, rng.uniform(1800, 3000), 1.5, sr) * 2.5
            if p['wet'] > 0:                                               # squelch
                w = _bp(rng.normal(0, 1, m).astype(np.float32), rng.uniform(300, 900), 4, sr)
                w *= np.exp(-tt * 12) * np.clip(tt / 0.02, 0, 1)
                hit += w * p['wet'] * 1.5
            e = min(n, s + m)
            out[s:e] += hit[:e - s]
            d0, d1 = s, min(n, s + int(rng.uniform(0.2, 0.5) * sr))
            drag[d0:d1] = np.maximum(drag[d0:d1], np.hanning(d1 - d0) * rng.uniform(0.4, 1))
        t += rng.uniform(0.5, 1.4) / max(p['speed'], 0.1)
    body = _bp(rng.normal(0, 1, n).astype(np.float32), 900, 0.8, sr) * drag * 0.35 * p['drag']
    out = out + body
    if p['distance'] > 0:
        out = _lp(out, 9000 - 7500 * p['distance'], sr) * (1 - 0.5 * p['distance'])
    return (np.tanh(out * 1.3) * 0.9).astype(np.float32)


def sfx_siren(p, sr, rng):
    """Air-raid (rotor) siren: slow rise, wailing hold with wobble, fall; horn resonance and overdrive.
    Siren Head = this + a garbled megaphone voice (see GUIDE.md, «Хоррор»)."""
    n = int(p['duration'] * sr)
    t = np.arange(n) / sr
    rise = max(p['rise'], 0.1)
    fall_start = p['duration'] - p['fall']
    up = 1 - np.exp(-t / (rise / 3))
    down = np.clip((p['duration'] - t) / max(p['fall'], 0.1), 0, 1) ** 1.5
    env_f = np.where(t < fall_start, up, up * down)
    f = p['pitch'] * (0.15 + 0.85 * env_f) * (1 + p['wobble'] * 0.03 * np.sin(2 * np.pi * 0.35 * t + rng.uniform(0, 6)))
    out = np.zeros(n, np.float32)
    for k, det in enumerate((1.0, 1.0 + p['chord'] * 0.26, 1.0 + p['chord'] * 0.5)):
        if k and not p['chord']:
            continue
        ph = 2 * np.pi * np.cumsum(f * det) / sr
        wave = sum(np.sin(h * ph) / h ** 0.8 for h in (1, 2, 3, 4, 5, 7, 9, 11))
        out += (wave / 3).astype(np.float32)
    horn = _bp(out, 1100, 1.0, sr) * 1.5 + _bp(out, 2300, 2, sr) * 0.6 + out * 0.3
    horn = np.tanh(horn * (1 + 3 * p['drive']))
    amp = np.clip(t / 0.3, 0, 1) * np.clip((p['duration'] - t) / 0.4, 0, 1) * (0.4 + 0.6 * env_f)
    return (horn * amp * 0.8).astype(np.float32)


HORROR_SFX = {
    'scrape': (sfx_scrape, {'duration': 4.0, 'material': 'stone', 'speed': 1.0, 'pressure': 0.7, 'grit': 0.6,
                            'claws': 3, 'squeal': 0.3},
               'Скрежет по стене: material stone|wood|metal|nails|glass, claws, pressure, squeal'),
    'crawl': (sfx_crawl, {'duration': 6.0, 'limbs': 4, 'speed': 1.0, 'weight': 0.6, 'claws': 0.7, 'drag': 0.7,
                          'wet': 0.0, 'bones': 0.0, 'distance': 0.0},
              'Кто-то ползёт: limbs, speed, weight, claws, drag, wet (мясо), bones (хруст), distance'),
    'siren': (sfx_siren, {'duration': 8.0, 'pitch': 460.0, 'rise': 3.0, 'fall': 2.5, 'wobble': 1.0, 'chord': 0.0,
                          'drive': 0.5},
              'Воздушная сирена (для Сиреноголового): pitch, rise, fall, chord (двутональная), drive'),
}


def fx_shimmer(x, sr, p, rng):
    """Shimmer reverb: the reverb tail is pitched up an octave and reverberated again — the «angelic» halo."""
    from .engine import fx_pitch_shift, fx_reverb
    size = float(p.get('size', 0.9))
    wet1 = fx_reverb(x, sr, {'size': size, 'mix': 1.0, 'damping': 0.3, 'predelay': 0.03}, rng)
    up = fx_pitch_shift(wet1, sr, {'semitones': float(p.get('semitones', 12)), 'grain': 0.1}, rng)
    wet2 = fx_reverb(up, sr, {'size': size, 'mix': 1.0, 'damping': 0.2, 'predelay': 0.05}, rng)
    n = max(len(x), len(wet1), len(wet2))
    pad = lambda a: np.pad(a, ((0, n - len(a)), (0, 0)))
    mix = float(p.get('mix', 0.45))
    return (pad(x) * (1 - mix) + (pad(wet1) * 0.7 + pad(wet2) * float(p.get('amount', 0.6))) * mix).astype(np.float32)
