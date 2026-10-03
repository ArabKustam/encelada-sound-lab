"""Additions to voice.py: Japanese lyrics (kana / romaji → singable syllables), voice-based horror SFX
(giggle, mimic, voice_scream, help_cry) and the WORLD formant effect.

Japanese: there is no Japanese Windows voice by default, so kana are sung by the Russian voice through the Polivanov
transcription (ки ми та ти га) — Russian vowels are close to Japanese ones, it sounds much more Japanese than English
TTS does. With lyrics in kana or `"lang": "ja"` + romaji this happens automatically.
"""
import re

import numpy as np

_TABLE = """
あ a а|い i и|う u у|え e э|お o о|か ka ка|き ki ки|く ku ку|け ke кэ|こ ko ко|さ sa са|し shi си|す su су|せ se сэ|そ so со
た ta та|ち chi ти|つ tsu цу|て te тэ|と to то|な na на|に ni ни|ぬ nu ну|ね ne нэ|の no но|は ha ха|ひ hi хи|ふ fu фу|へ he хэ|ほ ho хо
ま ma ма|み mi ми|む mu му|め me мэ|も mo мо|や ya я|ゆ yu ю|よ yo ё|ら ra ра|り ri ри|る ru ру|れ re рэ|ろ ro ро|わ wa ва|を wo о|ん n н
が ga га|ぎ gi ги|ぐ gu гу|げ ge гэ|ご go го|ざ za дза|じ ji дзи|ず zu дзу|ぜ ze дзэ|ぞ zo дзо|だ da да|ぢ di дзи|づ du дзу|で de дэ|ど do до
ば ba ба|び bi би|ぶ bu бу|べ be бэ|ぼ bo бо|ぱ pa па|ぴ pi пи|ぷ pu пу|ぺ pe пэ|ぽ po по|ゔ vu ву
きゃ kya кя|きゅ kyu кю|きょ kyo кё|しゃ sha ся|しゅ shu сю|しょ sho сё|ちゃ cha тя|ちゅ chu тю|ちょ cho тё|にゃ nya ня|にゅ nyu ню|にょ nyo нё
ひゃ hya хя|ひゅ hyu хю|ひょ hyo хё|みゃ mya мя|みゅ myu мю|みょ myo мё|りゃ rya ря|りゅ ryu рю|りょ ryo рё|ぎゃ gya гя|ぎゅ gyu гю|ぎょ gyo гё
じゃ ja дзя|じゅ ju дзю|じょ jo дзё|びゃ bya бя|びゅ byu бю|びょ byo бё|ぴゃ pya пя|ぴゅ pyu пю|ぴょ pyo пё|ふぁ fa фа|てぃ ti ти|でぃ dhi ди
"""
KANA, ROMAJI = {}, {}
for item in re.split(r'[|\n]', _TABLE):
    parts = item.split()
    if len(parts) == 3:
        KANA[parts[0]] = parts[2]
        ROMAJI[parts[1]] = parts[2]
ROMAJI.update({'si': 'си', 'ti': 'ти', 'tu': 'цу', 'hu': 'фу', 'zi': 'дзи', 'o': 'о', 'wo': 'о', 'nn': 'н', "n'": 'н'})
KANA_RE = re.compile('[぀-ヿ]')
VOWEL_OF = {'а': 'а', 'я': 'а', 'и': 'и', 'у': 'у', 'ю': 'у', 'э': 'э', 'е': 'э', 'о': 'о', 'ё': 'о', 'ы': 'ы'}


def _hira(text):
    return ''.join(chr(ord(c) - 0x60) if 'ァ' <= c <= 'ヶ' else c for c in text)


def kana_syllables(text):
    """'きみたちが' → ['ки', 'ми', 'та', 'ти', 'га']; ー extends the previous vowel, っ is a short stop (skipped)."""
    text = _hira(text)
    out = []
    i = 0
    while i < len(text):
        two, one = text[i:i + 2], text[i]
        if two in KANA:
            out.append(KANA[two])
            i += 2
        elif one in KANA:
            out.append(KANA[one])
            i += 1
        elif one == 'ー' and out:
            v = next((VOWEL_OF[c] for c in reversed(out[-1]) if c in VOWEL_OF), 'а')
            out.append(v)
            i += 1
        else:
            i += 1                                              # っ, spaces, punctuation
    return out


def romaji_syllables(text):
    """'ki mi ta chi ga' or 'kimitachiga' → Cyrillic syllables (longest match)."""
    out = []
    for word in re.split(r'[\s\-]+', text.lower()):
        i = 0
        while i < len(word):
            for size in (3, 2, 1):
                chunk = word[i:i + size]
                if chunk in ROMAJI:
                    if chunk == 'n' and i + 1 < len(word) and word[i + 1] in 'aiueoy':
                        continue
                    out.append(ROMAJI[chunk])
                    i += size
                    break
            else:
                if i + 1 < len(word) and word[i] == word[i + 1] and word[i] not in 'aiueon':   # double consonant (っ)
                    i += 1
                else:
                    i += 1
    return out


def singable(lyrics, lang='auto'):
    """Lyrics → list of syllables ready for TTS. Handles kana, romaji (lang='ja'), Russian/English with hyphens."""
    text = str(lyrics)
    if KANA_RE.search(text):
        return kana_syllables(text)
    if lang == 'ja':
        return romaji_syllables(text)
    return [s for s in re.split(r'[\s\-‐–]+', text) if s]


# ----------------------------------------------------------------------------------------------------- effects

def fx_formant(x, sr, p, rng):
    """Formant shift of a voice (WORLD): shift > 1 — smaller creature/child, < 1 — giant/monster; pitch_semitones too."""
    import pyworld as pw
    from .voice import _warp
    mono = x.mean(axis=1).astype(np.float64)
    fs = 22050
    y = np.interp(np.linspace(0, len(mono) - 1, int(len(mono) * fs / sr)), np.arange(len(mono)), mono)
    f0, t = pw.harvest(np.ascontiguousarray(y), fs, frame_period=5)
    sp = pw.cheaptrick(y, f0, t, fs)
    ap = pw.d4c(y, f0, t, fs)
    f0 = f0 * 2 ** (float(p.get('pitch_semitones', 0)) / 12)
    if p.get('monotone'):
        f0 = np.where(f0 > 0, float(p['monotone']), 0.0)
    out = pw.synthesize(f0, np.ascontiguousarray(_warp(sp, float(p.get('shift', 1.2)))), ap, fs, 5)
    out = np.interp(np.linspace(0, len(out) - 1, int(len(out) * sr / fs)), np.arange(len(out)), out).astype(np.float32)
    mix = float(p.get('mix', 1.0))
    n = min(len(out), len(x))
    res = x[:n] * (1 - mix) + out[:n, None] * mix
    return res.astype(np.float32)


# ----------------------------------------------------------------------------------------------------- voice SFX

def _syl(text, voice='auto', rate=-2):
    from . import voice as V
    return V.analyze_syllable(str(V.tts(text, voice, rate)))


def _to_sr(y, sr):
    from .voice import FS
    if sr == FS:
        return y
    return np.interp(np.arange(int(len(y) * sr / FS)) * FS / sr, np.arange(len(y)), y).astype(np.float32)


def sfx_giggle(p, sr, rng):
    """Creepy giggling of creatures in the dark: bursts of «хи-хи-хе» at random pitches from several voices."""
    from .voice import sing_note
    syl_opts = [_syl(s) for s in ('хи', 'хе', 'ки')]
    n = int(p['duration'] * sr)
    out = np.zeros(n, np.float32)
    t = 0.0
    for c in range(int(p['creatures'])):
        t = rng.uniform(0, p['duration'] * 0.4)
        base = p['pitch'] * rng.uniform(0.75, 1.35)
        formant = rng.uniform(1.05, 1.35) if p['small'] else rng.uniform(0.7, 1.0)
        while t < p['duration'] - 0.3:
            burst = int(rng.integers(3, 8))
            for k in range(burst):
                hz = base * (1 - 0.06 * k) * rng.uniform(0.95, 1.08)
                y, pre = sing_note(syl_opts[int(rng.integers(0, len(syl_opts)))], hz, rng.uniform(0.09, 0.16),
                                   vibrato=0, formant=formant, breath=p['breath'], rng=rng)
                y = _to_sr(y, sr) * rng.uniform(0.5, 1.0)
                s = int(t * sr)
                if s >= n - 1:
                    break
                e = min(n, s + len(y))
                out[s:e] += y[:e - s]
                t += rng.uniform(0.11, 0.2)
            t += rng.uniform(0.4, 1.6) / max(p['density'], 0.1)
    return out * 1.5


def sfx_voice_scream(p, sr, rng):
    """Human scream from a real voice: «а» with a rising-then-cracking pitch contour, strain, breath."""
    import pyworld as pw
    from .voice import FS, FRAME, _timemap, _warp
    syl = _syl(p['vowel'])
    dur = p['duration']
    pre = syl['v0']
    nv = syl['v1'] - syl['v0']
    target = int(dur * 1000 / FRAME)
    tm = _timemap(pre, nv, 0, target)
    i0 = np.floor(tm).astype(int)
    sp, ap = syl['sp'][i0], syl['ap'][i0]
    m = len(tm)
    x = np.linspace(0, 1, m)
    contour = p['pitch'] * (0.75 + 0.45 * np.clip(x / 0.12, 0, 1)) * (1 - 0.3 * np.clip((x - 0.75) / 0.25, 0, 1) ** 2)
    shake = 1 + 0.04 * p['rough'] * np.sin(2 * np.pi * 9 * x * dur) + 0.03 * p['rough'] * rng.normal(0, 1, m)
    f0 = np.where(syl['f0'][i0] > 0, contour * shake, 0.0)
    ap = np.clip(ap + 0.15 + 0.35 * p['rough'], 0, 1)
    y = pw.synthesize(np.ascontiguousarray(f0), np.ascontiguousarray(_warp(sp, p['formant'])), np.ascontiguousarray(ap), FS, FRAME)
    y = np.tanh(y * (3 + 6 * p['rough'])) * 0.8
    fade = int(0.05 * FS)
    y[-fade:] *= np.linspace(1, 0, fade)
    return _to_sr(y.astype(np.float32), sr)


def sfx_mimic(p, sr, rng):
    """A mimic calling for help: the phrase repeats, each time a little wrong — pitch jumps, stutters, stretched or
    reversed pieces, drifting formants, one repeat almost right. text: what it says."""
    import pyworld as pw
    from . import voice as V
    path = V.tts(p['text'], p.get('voice', 'auto'), 0)
    import soundfile as sf
    x, fs = sf.read(str(path), dtype='float64')
    x = np.ascontiguousarray(x if x.ndim == 1 else x.mean(axis=1))
    f0, t = pw.harvest(x, fs, frame_period=5)
    sp = pw.cheaptrick(x, f0, t, fs)
    ap = pw.d4c(x, f0, t, fs)
    energy = sp.mean(axis=1)
    loud = np.nonzero(10 * np.log10(energy + 1e-12) > 10 * np.log10(energy.max()) - 45)[0]
    a, b = (loud[0], loud[-1] + 1) if len(loud) else (0, len(f0))
    f0, sp, ap = f0[a:b], sp[a:b], ap[a:b]
    out = []
    wrong = p['wrongness']
    for rep in range(int(p['count'])):
        w = wrong * (0.3 if rep == 0 else rng.uniform(0.6, 1.3))
        n = len(f0)
        idx = np.arange(n, dtype=float)
        if rng.uniform() < w:                                  # stutter the beginning
            k = int(rng.integers(8, 30))
            idx = np.concatenate([idx[:k]] * int(rng.integers(2, 4)) + [idx])
        if rng.uniform() < w * 0.8:                            # slow/drag a part
            s = int(rng.integers(0, max(1, n // 2)))
            e = min(n, s + int(rng.integers(20, 60)))
            idx = np.concatenate([idx[:s], np.linspace(s, e, (e - s) * int(rng.integers(2, 4))), idx[e:]])
        ii = np.clip(idx.astype(int), 0, n - 1)
        pitch = 2 ** (rng.normal(0, 3 * w) / 12) * (1 + 0.15 * w * np.sin(np.linspace(0, rng.uniform(2, 9), len(ii))))
        ff = np.where(f0[ii] > 0, f0[ii] * pitch * p['pitch'], 0.0)
        if rng.uniform() < w * 0.5:
            ff = np.where(ff > 0, np.median(ff[ff > 0]) if (ff > 0).any() else 0, 0.0)   # monotone, lifeless
        form = p['formant'] * 2 ** (rng.normal(0, 0.12 * w))
        y = pw.synthesize(np.ascontiguousarray(ff), np.ascontiguousarray(V._warp(sp[ii], form)), np.ascontiguousarray(ap[ii]), fs, 5)
        if rng.uniform() < w * 0.35:                           # a reversed tail
            cut = int(len(y) * rng.uniform(0.5, 0.8))
            y = np.concatenate([y[:cut], y[cut:][::-1]])
        out.append(y)
        out.append(np.zeros(int(fs * rng.uniform(0.5, 1.5) * p['pause'])))
    y = np.concatenate(out).astype(np.float32)
    y = np.interp(np.arange(int(len(y) * sr / fs)) * fs / sr, np.arange(len(y)), y).astype(np.float32)
    return y


VOICE_SFX = {
    'giggle': (sfx_giggle, {'duration': 6.0, 'creatures': 3, 'pitch': 420.0, 'small': True, 'breath': 0.35,
                            'density': 1.0}, 'Хихиканье существ в темноте (голос)'),
    'voice_scream': (sfx_voice_scream, {'duration': 2.0, 'pitch': 520.0, 'rough': 0.6, 'vowel': 'а', 'formant': 1.0},
                     'Крик живым голосом'),
    'mimic': (sfx_mimic, {'text': 'Помогите! Пожалуйста, помогите', 'count': 4, 'wrongness': 0.7, 'pitch': 1.0,
                          'formant': 1.0, 'pause': 1.0, 'voice': 'auto'},
              'Мимик зовёт на помощь: фраза повторяется, каждый раз «не так»'),
}
