"""Listening for someone who cannot listen: numbers + plain-language notes about a rendered sound.

analyze(x, sr) → loudness (peak/RMS, over time), silence at the ends, clipping, frequency balance by band, brightness,
stereo width, onsets, tempo estimate, key estimate, pitch of a short sample, and warnings.
"""
import math

import numpy as np
from scipy import signal

PITCH_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
BANDS = [('sub', 20, 60), ('bass', 60, 250), ('low_mid', 250, 2000), ('high_mid', 2000, 6000), ('air', 6000, 20000)]


def _db(v):
    return round(20 * math.log10(max(float(v), 1e-9)), 1)


def _stft(mono, n_fft=2048, hop=512):
    if len(mono) < n_fft:
        mono = np.pad(mono, (0, n_fft - len(mono)))
    frames = 1 + (len(mono) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(frames)[:, None]
    return np.abs(np.fft.rfft(mono[idx] * np.hanning(n_fft)[None, :], axis=1)).astype(np.float32)


def midi_name(m):
    m = int(round(m))
    return f'{PITCH_NAMES[m % 12]}{m // 12 - 1}'


def estimate_pitch(mono, sr):
    """Fundamental of the loudest 0.1 s (autocorrelation). Returns (hz, clarity) or (None, 0)."""
    win = int(0.1 * sr)
    if len(mono) < win:
        return None, 0.0
    energy = np.convolve(mono ** 2, np.ones(win // 4), mode='valid')[::win // 4]
    s = int(np.argmax(energy)) * (win // 4)
    seg = mono[s:s + win]
    seg = seg - seg.mean()
    ac = signal.fftconvolve(seg, seg[::-1])[len(seg) - 1:]
    if ac[0] <= 0:
        return None, 0.0
    ac /= ac[0]
    lo, hi = int(sr / 2000), int(sr / 40)
    if hi >= len(ac):
        return None, 0.0
    neg = np.nonzero(ac[:hi] < 0)[0]                                    # skip the zero-lag lobe
    lo = max(lo, int(neg[0])) if len(neg) else lo
    lag = lo + int(np.argmax(ac[lo:hi]))
    clarity = float(ac[lag])
    if clarity < 0.45:
        return None, clarity
    if 0 < lag < len(ac) - 1:                                            # parabolic interpolation
        a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
        den = a - 2 * b + c
        if den < 0:
            lag = lag + float(np.clip(0.5 * (a - c) / den, -0.5, 0.5))
    return (sr / lag, clarity) if lag > 0 else (None, 0.0)


def analyze(x, sr):
    x = np.asarray(x, dtype=np.float32)
    if x.ndim == 1:
        x = np.stack([x, x], 1)
    elif x.shape[1] == 1:
        x = np.repeat(x, 2, axis=1)
    mono = x.mean(axis=1)
    dur = len(mono) / sr
    peak = float(np.abs(x).max()) if len(x) else 0.0
    rms = float(np.sqrt(np.mean(mono ** 2))) if len(mono) else 0.0
    out = {'seconds': round(dur, 2), 'peak_db': _db(peak), 'rms_db': _db(rms), 'crest_db': round(_db(peak) - _db(rms), 1),
           'clipped_percent': round(100 * float(np.mean(np.abs(x) > 0.999)), 3)}

    # loudness over time
    n_win = int(min(32, max(4, dur * 2)))
    edges = np.linspace(0, len(mono), n_win + 1).astype(int)
    out['loudness_timeline_db'] = [_db(np.sqrt(np.mean(mono[a:b] ** 2)) if b > a else 0) for a, b in zip(edges[:-1], edges[1:])]
    out['timeline_step_s'] = round(dur / n_win, 2)
    thr = peak * 10 ** (-60 / 20)
    loud = np.nonzero(np.abs(mono) > thr)[0]
    out['silence_start_s'] = round(loud[0] / sr, 2) if len(loud) else round(dur, 2)
    out['silence_end_s'] = round((len(mono) - loud[-1]) / sr, 2) if len(loud) else round(dur, 2)

    # spectrum
    spec = _stft(mono)
    power = (spec ** 2).mean(axis=0)
    freqs = np.fft.rfftfreq(2048, 1 / sr)
    total = float(power.sum()) or 1.0
    out['bands_percent'] = {name: round(100 * float(power[(freqs >= lo) & (freqs < hi)].sum()) / total, 1) for name, lo, hi in BANDS}
    out['brightness_hz'] = int(float((freqs * power).sum()) / total)
    cum = np.cumsum(power) / total
    out['rolloff85_hz'] = int(freqs[min(len(freqs) - 1, int(np.searchsorted(cum, 0.85)))])

    # stereo
    l, r = x[:, 0], x[:, 1]
    mid, side = (l + r) / 2, (l - r) / 2
    out['stereo_width'] = round(float(np.sqrt(np.mean(side ** 2)) / (np.sqrt(np.mean(mid ** 2)) + 1e-9)), 2)
    den = float(np.sqrt(np.sum(l ** 2) * np.sum(r ** 2))) or 1.0
    out['lr_correlation'] = round(float(np.sum(l * r)) / den, 2)

    # onsets & tempo
    logspec = np.log1p(spec * 10)
    flux = np.maximum(0, np.diff(logspec, axis=0)).sum(axis=1)
    hop_s = 512 / sr
    if len(flux) > 8:
        flux = flux - np.convolve(flux, np.ones(16) / 16, mode='same')
        flux = np.maximum(flux, 0)
        thr_o = flux.mean() + 1.5 * flux.std()
        peaks, _ = signal.find_peaks(flux, height=thr_o, distance=max(1, int(0.07 / hop_s)))
        onsets = peaks * hop_s
        out['onsets'] = len(onsets)
        out['onsets_per_s'] = round(len(onsets) / max(dur, 1e-3), 2)
        out['first_onsets_s'] = [round(float(o), 2) for o in onsets[:16]]
        if dur > 3 and len(onsets) >= 6:
            env = flux - flux.mean()
            ac = np.correlate(env, env, mode='full')[len(env) - 1:]
            lags = np.arange(len(ac)) * hop_s
            ok = (lags >= 60 / 200) & (lags <= 60 / 55)
            if ok.any():
                best = lags[ok][int(np.argmax(ac[ok]))]
                bpm = 60 / best
                while bpm < 70:
                    bpm *= 2
                while bpm > 180:
                    bpm /= 2
                out['tempo_bpm_estimate'] = round(bpm, 1)

    # key (chroma) and pitch
    band = (freqs > 55) & (freqs < 4200)
    midi = 69 + 12 * np.log2(freqs[band] / 440.0)
    chroma = np.zeros(12)
    np.add.at(chroma, np.round(midi).astype(int) % 12, power[band])
    if chroma.sum() > 0 and dur > 1.5:
        c = chroma / chroma.sum()
        best = max(((float(np.corrcoef(c, np.roll(prof, k))[0, 1]), k, mode)
                    for k in range(12) for prof, mode in ((MAJOR, 'major'), (MINOR, 'minor'))))
        out['key_estimate'] = f'{PITCH_NAMES[best[1]]} {best[2]}'
        out['key_confidence'] = round(best[0], 2)
        out['strongest_pitch_classes'] = [PITCH_NAMES[i] for i in np.argsort(c)[::-1][:4]]
    hz, clarity = estimate_pitch(mono, sr) if dur <= 8 else (None, 0.0)
    if hz:
        m = 69 + 12 * math.log2(hz / 440)
        out['pitch'] = {'hz': round(hz, 1), 'note': midi_name(m), 'cents_off': int(round((m - round(m)) * 100)),
                        'clarity': round(clarity, 2)}
    out['notes'] = notes(out)
    return out


def notes(a):
    """Plain-language observations (Russian, like the rest of the UI)."""
    w = []
    if a['clipped_percent'] > 0.05:
        w.append(f'клиппинг: {a["clipped_percent"]}% сэмплов в потолке — убавьте gain или drive')
    if a['peak_db'] < -12:
        w.append('очень тихо — поднимите normalize мастера')
    if a['crest_db'] < 6:
        w.append('пережато (crest < 6 дБ): мало динамики, звук «плоский»')
    elif a['crest_db'] > 22:
        w.append('очень большая динамика — тихие места могут потеряться в игре')
    b = a['bands_percent']
    if b['sub'] + b['bass'] > 85:
        w.append('низы доминируют (>85%) — в Minecraft на ноутбучных динамиках будет «бубнёж»; highpass/eq low -')
    if b['high_mid'] + b['air'] > 45:
        w.append('много высоких (>45%) — может резать уши; lowpass или eq high -')
    if b['low_mid'] > 75:
        w.append('всё в середине — мутновато; добавьте низ (бас) или воздух (hat, реверб)')
    if a['silence_start_s'] > 0.15:
        w.append(f'тишина в начале {a["silence_start_s"]} с — для SFX лучше срезать (trim)')
    if a['silence_end_s'] > 1.0:
        w.append(f'тишина в конце {a["silence_end_s"]} с')
    if a['lr_correlation'] < 0.2 and a['stereo_width'] > 0.8:
        w.append('очень широкое/фазовое стерео — в моно (звуки «в мире») часть пропадёт')
    tl = a['loudness_timeline_db'][1:-1]                                  # края — это вступление/затухание
    if len(tl) > 4 and max(tl) - min(tl) > 30:
        w.append(f'громкость сильно меняется во времени ({min(tl)}…{max(tl)} дБ)')
    if not w:
        w.append('явных проблем не видно')
    return w


def analyze_file(path):
    import soundfile as sf
    x, sr = sf.read(str(path), dtype='float32', always_2d=True)
    return analyze(x, sr)
