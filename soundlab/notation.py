"""Compact music notation → explicit notes. This is what makes recipes quick to write by hand (or by Claude):

    melody:  "C4:1 E G:1/2 A | [C4 E G]:2 r:1 (C5 D E)x2 > C:4@0.9"
    chords:  "Am F C G"  or  "i VI III VII" (needs key)  with style block|pulse|strum|arp|arp_down|arp_updown|alberti|root|root_fifth
    drums:   {"kick": "x...x...x...x...", "snare": "....x.......x...", "hat": "x.x.x.x.x.x.x.x."}
    parts + sections + arrange: song structure (intro / verse / chorus …)

`expand_recipe(recipe)` returns a recipe where every notes track has an explicit `notes` list and a resolved
`instrument` dict — the form the engine renders. The original compact recipe stays the source of truth.
Full syntax: GUIDE.md.
"""
import copy
import math
import random
import re

NOTE_BASE = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
PITCH_RE = re.compile(r'^([A-Ga-g])(##|#|bb|b|s)?(-?\d)?$')
SUFFIX_RE = re.compile(r'^(?::(?P<dur>[0-9./]+|[whqest]\.?))?(?P<acc>[!?]*)(?:@(?P<vel>[0-9.]+))?$')
DUR_LETTERS = {'w': 4.0, 'h': 2.0, 'q': 1.0, 'e': 0.5, 's': 0.25, 't': 1 / 3}
TOKEN_RE = re.compile(r'\[[^\]]*\][^\s()\[\]]*|\(|\)(?:[x*]\d+)?|[^\s()\[\]]+')

CHORD_QUALITIES = {
    '': [0, 4, 7], 'maj': [0, 4, 7], 'M': [0, 4, 7], 'm': [0, 3, 7], 'min': [0, 3, 7], '5': [0, 7],
    '6': [0, 4, 7, 9], 'm6': [0, 3, 7, 9], '7': [0, 4, 7, 10], 'maj7': [0, 4, 7, 11], 'M7': [0, 4, 7, 11],
    'm7': [0, 3, 7, 10], 'mmaj7': [0, 3, 7, 11], 'm7b5': [0, 3, 6, 10], 'ø': [0, 3, 6, 10], 'ø7': [0, 3, 6, 10],
    'dim': [0, 3, 6], '°': [0, 3, 6], 'o': [0, 3, 6], 'dim7': [0, 3, 6, 9], '°7': [0, 3, 6, 9], 'o7': [0, 3, 6, 9],
    'aug': [0, 4, 8], '+': [0, 4, 8], 'sus2': [0, 2, 7], 'sus4': [0, 5, 7], 'sus': [0, 5, 7], '7sus4': [0, 5, 7, 10],
    'add9': [0, 4, 7, 14], 'madd9': [0, 3, 7, 14], '9': [0, 4, 7, 10, 14], 'maj9': [0, 4, 7, 11, 14],
    'm9': [0, 3, 7, 10, 14], '11': [0, 4, 7, 10, 14, 17], 'm11': [0, 3, 7, 10, 14, 17], '13': [0, 4, 7, 10, 14, 21],
}
CHORD_RE = re.compile(r'^([A-G])(#|b)?(' + '|'.join(sorted(map(re.escape, CHORD_QUALITIES), key=len, reverse=True))
                      + r')(?:/([A-G](?:#|b)?))?$')
ROMAN = {'I': 0, 'II': 1, 'III': 2, 'IV': 3, 'V': 4, 'VI': 5, 'VII': 6}
ROMAN_RE = re.compile(r'^(b|#)?(VII|VI|IV|V|III|II|I|vii|vi|iv|v|iii|ii|i)(maj7|maj9|m7b5|ø7|ø|°7|°|o7|o|dim7|dim|\+|aug|7|9|sus2|sus4|add9|6)?$')
MODES = {'major': [0, 2, 4, 5, 7, 9, 11], 'minor': [0, 2, 3, 5, 7, 8, 10], 'dorian': [0, 2, 3, 5, 7, 9, 10],
         'phrygian': [0, 1, 3, 5, 7, 8, 10], 'lydian': [0, 2, 4, 6, 7, 9, 11], 'mixolydian': [0, 2, 4, 5, 7, 9, 10],
         'harmonic_minor': [0, 2, 3, 5, 7, 8, 11]}

GRID_HITS = {'x': 0.85, 'X': 1.0, 'o': 0.55, 'O': 0.7, 'g': 0.3, 'r': 0.7, 'R': 0.9, 't': 0.7}
GRID_ROLLS = {'r': 2, 'R': 2, 't': 3}
GRID_SKIP = set(' |\n\t')

GM_DRUM_KEYS = {
    'kick': 36, 'kick2': 35, 'bd': 36, 'snare': 38, 'snare2': 40, 'sd': 38, 'rim': 37, 'sidestick': 37, 'clap': 39,
    'hat': 42, 'hh': 42, 'chh': 42, 'phat': 44, 'pedal': 44, 'ohat': 46, 'oh': 46, 'ohh': 46,
    'tom1': 50, 'tom_high': 50, 'tom2': 47, 'tom_mid': 47, 'tom3': 45, 'tom_low': 45, 'tom': 47, 'floor': 41,
    'crash': 49, 'crash2': 57, 'ride': 51, 'ridebell': 53, 'bell': 53, 'china': 52, 'splash': 55, 'tamb': 54,
    'tambourine': 54, 'cowbell': 56, 'shaker': 70, 'maracas': 70, 'cabasa': 69, 'clave': 75, 'woodblock': 76,
    'conga': 63, 'conga_low': 64, 'bongo': 60, 'bongo_low': 61, 'triangle': 81, 'vibraslap': 58, 'whistle': 71,
}

GM_ALIASES = {
    0: 'piano пианино фортепиано рояль grand_piano acoustic_piano', 1: 'bright_piano', 3: 'honky_tonk хонки-тонк',
    4: 'electric_piano rhodes электропиано', 6: 'harpsichord клавесин', 7: 'clavinet клавинет', 8: 'celesta челеста',
    9: 'glockenspiel глокеншпиль колокольчики', 10: 'music_box', 11: 'vibraphone вибрафон', 12: 'marimba маримба',
    13: 'xylophone ксилофон', 14: 'tubular_bells колокола', 15: 'dulcimer', 16: 'organ орган drawbar_organ',
    18: 'rock_organ', 19: 'church_organ церковный_орган', 21: 'accordion аккордеон баян', 22: 'harmonica губная_гармошка',
    24: 'nylon_guitar classical_guitar классическая_гитара', 25: 'guitar гитара acoustic_guitar акустическая_гитара',
    26: 'jazz_guitar джаз_гитара', 27: 'electric_guitar электрогитара clean_guitar', 28: 'muted_guitar',
    29: 'overdrive_guitar overdriven_guitar перегруз', 30: 'distortion_guitar дисторшн rock_guitar рок_гитара',
    31: 'guitar_harmonics', 32: 'acoustic_bass', 33: 'bass_guitar бас-гитара бас_гитара finger_bass electric_bass бас',
    34: 'pick_bass', 35: 'fretless_bass фретлес', 36: 'slap_bass слэп', 38: 'synth_bass синт-бас', 40: 'violin скрипка',
    41: 'viola альт', 42: 'cello виолончель', 43: 'contrabass double_bass контрабас', 44: 'tremolo_strings тремоло',
    45: 'pizzicato пиццикато', 46: 'harp арфа', 47: 'timpani литавры', 48: 'strings струнные string_ensemble оркестр',
    49: 'slow_strings', 50: 'synth_strings', 52: 'choir хор aahs', 53: 'voice голос oohs', 54: 'synth_voice',
    55: 'orchestra_hit оркестровый_удар', 56: 'trumpet труба', 57: 'trombone тромбон', 58: 'tuba туба',
    59: 'muted_trumpet', 60: 'french_horn horn валторна', 61: 'brass духовые brass_section', 62: 'synth_brass',
    64: 'soprano_sax', 65: 'sax saxophone саксофон alto_sax', 66: 'tenor_sax', 67: 'baritone_sax', 68: 'oboe гобой',
    69: 'english_horn', 70: 'bassoon фагот', 71: 'clarinet кларнет', 72: 'piccolo пикколо', 73: 'flute флейта',
    74: 'recorder блокфлейта', 75: 'pan_flute пан-флейта', 77: 'shakuhachi', 78: 'whistle свист', 79: 'ocarina окарина',
    80: 'square_lead chiptune_lead', 81: 'saw_lead lead synth_lead', 88: 'new_age_pad', 89: 'warm_pad',
    90: 'polysynth', 91: 'choir_pad', 92: 'bowed_pad', 93: 'metallic_pad', 94: 'halo_pad', 95: 'sweep_pad',
    96: 'rain', 98: 'crystal', 99: 'atmosphere', 101: 'goblins', 102: 'echoes', 103: 'sci-fi scifi',
    104: 'sitar ситар', 105: 'banjo банджо', 106: 'shamisen', 107: 'koto кото', 108: 'kalimba калимба',
    109: 'bagpipe волынка', 110: 'fiddle', 114: 'steel_drums steel_drum стил-драм', 115: 'woodblock', 116: 'taiko тайко',
    117: 'melodic_tom', 118: 'synth_drum', 119: 'reverse_cymbal', 122: 'seashore прибой', 123: 'bird птицы',
    124: 'telephone телефон', 125: 'helicopter вертолёт', 126: 'applause аплодисменты', 127: 'gunshot выстрел',
}
ALIAS_TO_GM = {a.replace('_', ' '): n for n, names in GM_ALIASES.items() for a in names.split()}
SYNTH_ALIASES = {'шкатулка': 'musicbox', 'music box synth': 'musicbox', 'пэд': 'pad', 'колокол': 'bell',
                 'щипок': 'pluck', 'пила': 'saw', 'квадрат': 'square', 'треугольник': 'triangle', 'синус': 'sine'}
DRUM_WORDS = {'drums', 'drum', 'барабаны', 'ударные', 'gm_drums', 'kit', 'drumkit'}


class NotationError(ValueError):
    pass


# ----------------------------------------------------------------------------------------------------- basics

def pitch_class(name):
    m = re.match(r'^([A-Ga-g])(#|b)?$', name)
    if not m:
        raise NotationError(f'не понимаю тонику {name!r}')
    return (NOTE_BASE[m.group(1).upper()] + (1 if m.group(2) == '#' else -1 if m.group(2) == 'b' else 0)) % 12


def parse_key(key):
    """'C', 'Am', 'A minor', 'F# dorian' → (tonic pitch class, mode name)."""
    if not key:
        return 0, 'major'
    k = str(key).strip().replace('_', ' ')
    parts = k.split()
    tonic = parts[0]
    mode = parts[1].lower() if len(parts) > 1 else None
    if mode is None:
        if tonic.endswith('min') and len(tonic) > 3:
            tonic, mode = tonic[:-3], 'minor'
        elif tonic.endswith('m') and len(tonic) > 1:
            tonic, mode = tonic[:-1], 'minor'
        else:
            mode = 'major'
    mode ={'maj': 'major', 'min': 'minor', 'moll': 'minor', 'dur': 'major', 'минор': 'minor', 'мажор': 'major'}.get(mode, mode)
    if mode not in MODES:
        raise NotationError(f'не знаю лад {mode!r}; есть: {", ".join(MODES)}')
    return pitch_class(tonic), mode


def parse_duration(text, default):
    if not text:
        return default
    dotted = text.endswith('.') and text[:-1] in DUR_LETTERS
    t = text[:-1] if dotted else text
    if t in DUR_LETTERS:
        d = DUR_LETTERS[t]
    elif '/' in t:
        a, b = t.split('/', 1)
        d = float(a or 1) / float(b)
    else:
        d = float(t)
    return d * (1.5 if dotted else 1.0)


def note_number(token, octave):
    """'C4' → 60; 'C' → uses `octave`; '60' → 60. Returns (midi, octave_used)."""
    if re.fullmatch(r'\d+(\.\d+)?', token):
        return float(token), octave
    m = PITCH_RE.match(token)
    if not m:
        raise NotationError(f'не понимаю ноту {token!r} (пример: C4, F#3, Bb, 60)')
    acc = m.group(2) or ''
    shift = {'#': 1, 's': 1, '##': 2, 'b': -1, 'bb': -2, '': 0}[acc]
    octv = int(m.group(3)) if m.group(3) is not None else octave
    return float(NOTE_BASE[m.group(1).upper()] + shift + 12 * (octv + 1)), octv


def chord_intervals(symbol, key=None):
    """Chord symbol or roman numeral → (root pitch class, intervals, slash bass pitch class | None)."""
    m = CHORD_RE.match(symbol)
    if m:
        root = pitch_class(m.group(1) + (m.group(2) or ''))
        bass = pitch_class(m.group(4)) if m.group(4) else None
        return root, CHORD_QUALITIES[m.group(3)], bass
    m = ROMAN_RE.match(symbol)
    if m:
        tonic, mode = parse_key(key)
        scale = MODES[mode]
        num = m.group(2)
        root = (tonic + scale[ROMAN[num.upper()]] + {'b': -1, '#': 1, None: 0}[m.group(1)]) % 12
        minor = num.islower()
        q = m.group(3) or ''
        if q in ('°', 'o', 'dim'):
            iv = [0, 3, 6]
        elif q in ('°7', 'o7', 'dim7'):
            iv = [0, 3, 6, 9]
        elif q in ('ø', 'ø7', 'm7b5'):
            iv = [0, 3, 6, 10]
        elif q in ('+', 'aug'):
            iv = [0, 4, 8]
        elif q == '7':
            iv = [0, 3, 7, 10] if minor else [0, 4, 7, 10]
        elif q == '9':
            iv = [0, 3, 7, 10, 14] if minor else [0, 4, 7, 10, 14]
        elif q in ('maj7', 'maj9'):
            iv = [0, 4, 7, 11] + ([14] if q == 'maj9' else [])
        elif q in ('sus2', 'sus4', 'add9', '6'):
            iv = CHORD_QUALITIES[('m' if minor and q in ('add9', '6') else '') + q]
        else:
            iv = [0, 3, 7] if minor else [0, 4, 7]
        return root, iv, None
    raise NotationError(f'не понимаю аккорд {symbol!r} (пример: Am, F#m7, Cmaj7, G/B, Dsus4; или ступени i iv V7 при key)')


def chord_notes(symbol, octave=3, key=None, bass=False):
    root, iv, slash = chord_intervals(symbol, key)
    base = 12 * (octave + 1) + root
    notes = [base + i for i in iv]
    if slash is not None:
        notes.insert(0, 12 * octave + slash if 12 * octave + slash < base else 12 * (octave - 1) + slash)
    elif bass:
        notes.insert(0, base - 12)
    return [float(n) for n in notes]


# ----------------------------------------------------------------------------------------------------- melody

def parse_melody(text, length=1.0, velocity=0.8, octave=4, key=None):
    """Melody string → (notes [[start, len, midi, vel]], total beats)."""
    tokens = TOKEN_RE.findall(str(text))
    st = {'t': 0.0, 'dur': float(length), 'oct': int(octave), 'last': []}
    notes = []

    def suffix(s, tok):
        m = SUFFIX_RE.match(s)
        if not m:
            raise NotationError(f'не понимаю {tok!r}: после ноты пишите :длина, !/? (акцент/тихо), @громкость')
        st['dur'] = parse_duration(m.group('dur'), st['dur'])
        vel = float(m.group('vel')) if m.group('vel') else velocity
        vel += 0.15 * m.group('acc').count('!') - 0.25 * m.group('acc').count('?')
        return st['dur'], float(min(1.0, max(0.05, vel)))

    def run(toks):
        i = 0
        while i < len(toks):
            tok = toks[i]
            if tok == '(':
                depth, j = 1, i + 1
                while j < len(toks) and depth:
                    depth += 1 if toks[j] == '(' else -1 if toks[j].startswith(')') else 0
                    j += 1
                if depth:
                    raise NotationError('не закрыта скобка ( … )')
                close = toks[j - 1]
                times = int(close[2:]) if len(close) > 1 else 1
                for _ in range(times):
                    run(toks[i + 1:j - 1])
                i = j
                continue
            if tok.startswith(')'):
                raise NotationError('лишняя закрывающая скобка )')
            i += 1
            if set(tok) <= set('|'):
                continue
            if set(tok) <= set('<>'):
                st['oct'] += tok.count('>') - tok.count('<')
                continue
            if re.fullmatch(r'o-?\d', tok):
                st['oct'] = int(tok[1:])
                continue
            if tok.startswith('['):
                inner, rest = tok[1:].split(']', 1)
                dur, vel = suffix(rest, tok)
                items = inner.split()
                pitches = []
                if len(items) == 1 and not PITCH_RE.match(items[0]) and not items[0].isdigit():
                    pitches = chord_notes(items[0], st['oct'], key)
                else:
                    prev = None
                    for it in items:
                        m, o = note_number(it, st['oct'])
                        if prev is not None and not re.search(r'\d$', it):
                            while m <= prev:
                                m += 12
                        pitches.append(m)
                        prev = m
                        if re.search(r'-?\d$', it) and not it.isdigit():
                            st['oct'] = o
                st['last'] = []
                for p in pitches:
                    st['last'].append(len(notes))
                    notes.append([st['t'], dur, p, vel])
                st['t'] += dur
                continue
            head = re.match(r'^([^:!?@]+)(.*)$', tok)
            if not head:
                raise NotationError(f'не понимаю {tok!r}')
            name, rest = head.group(1), head.group(2)
            if name in ('r', 'R', '.', '_'):
                dur, _ = suffix(rest, tok)
                st['t'] += dur
                st['last'] = []
                continue
            if name in ('-', '~'):
                dur, _ = suffix(rest, tok)
                for k in st['last']:
                    notes[k][1] += dur
                st['t'] += dur
                continue
            m, o = note_number(name, st['oct'])
            st['oct'] = o
            dur, vel = suffix(rest, tok)
            st['last'] = [len(notes)]
            notes.append([st['t'], dur, m, vel])
            st['t'] += dur

    run(tokens)
    return notes, st['t']


# ----------------------------------------------------------------------------------------------------- chords

def parse_chords(text, style='block', octave=3, length=4.0, velocity=0.7, key=None, arp_step=0.5, pulse=1.0,
                 strum=0.04, bass=False, gate=0.95):
    """Chord progression → (notes, total beats)."""
    notes = []
    t = 0.0
    dur = float(length)
    prev = None
    for tok in str(text).split():
        if set(tok) <= set('|'):
            continue
        name, _, d = tok.partition(':')
        dur = parse_duration(d, dur) if d else dur
        if name in ('r', '.', '_'):
            t += dur
            continue
        if name == '%':
            if prev is None:
                raise NotationError('% (повтор) до первого аккорда')
            name = prev
        prev = name
        ch = chord_notes(name, octave, key, bass)
        root = ch[0]
        upper = ch[1:] if (bass or '/' in name) else ch
        if style == 'block':
            notes += [[t, dur * gate, n, velocity] for n in ch]
        elif style == 'pulse':
            k = 0.0
            while k < dur - 1e-6:
                notes += [[t + k, min(pulse, dur - k) * gate, n, velocity * (1.0 if k == 0 else 0.85)] for n in ch]
                k += pulse
        elif style == 'strum':
            notes += [[t + i * strum, dur - i * strum, n, velocity * (1 - 0.04 * i)] for i, n in enumerate(ch)]
        elif style in ('arp', 'arp_up', 'arp_down', 'arp_updown', 'alberti'):
            seq = upper if len(upper) >= 2 else ch
            if style == 'arp_down':
                seq = seq[::-1]
            elif style == 'arp_updown':
                seq = seq + seq[-2:0:-1]
            elif style == 'alberti':
                seq = [seq[0], seq[min(2, len(seq) - 1)], seq[1], seq[min(2, len(seq) - 1)]]
            if bass or '/' in name:
                notes.append([t, dur * gate, root, velocity])
            k, i = 0.0, 0
            while k < dur - 1e-6:
                notes.append([t + k, min(arp_step, dur - k) * gate, seq[i % len(seq)], velocity * (1.0 if i == 0 else 0.85)])
                k += arp_step
                i += 1
        elif style in ('root', 'root_fifth', 'root_octave'):
            r = min(ch) if ('/' in name) else ch[0] - (12 if not bass else 0)
            alt = {'root': r, 'root_fifth': r + 7, 'root_octave': r + 12}[style]
            k, i = 0.0, 0
            while k < dur - 1e-6:
                notes.append([t + k, min(pulse, dur - k) * gate, r if i % 2 == 0 else alt, velocity])
                k += pulse
                i += 1
        else:
            raise NotationError(f'нет стиля аккордов {style!r}: block pulse strum arp arp_down arp_updown alberti root root_fifth root_octave')
        t += dur
    return notes, t


# ----------------------------------------------------------------------------------------------------- drum grid

def parse_grid(rows, step=0.25, swing=0.0, velocity=1.0):
    """{'kick': 'x...x...', 'mc:note/hat': {'p': 'x.x.', 'pitch': 3, 'gain': 0.6}} → (notes, total beats).
    Notes: [start, length, row_name, vel, {opts}]."""
    notes = []
    total = 0.0
    for row, spec in rows.items():
        opts = {}
        if isinstance(spec, dict):
            pattern = spec.get('p') or spec.get('pattern', '')
            opts = {k: v for k, v in spec.items() if k in ('pitch', 'gain', 'length', 'sample', 'note')}
            row_step = float(spec.get('step', step))
        else:
            pattern, row_step = spec, step
        cells = [c for c in str(pattern) if c not in GRID_SKIP]
        total = max(total, len(cells) * row_step)
        for i, c in enumerate(cells):
            if c in '.-_':
                continue
            if c.isdigit():
                vel = max(0.1, int(c) / 9)
            elif c in GRID_HITS:
                vel = GRID_HITS[c]
            else:
                raise NotationError(f'в сетке «{row}» неизвестный символ {c!r}: x X o O g r R t 1-9 и . - _ для пауз')
            start = i * row_step + (swing * row_step if i % 2 == 1 else 0.0)
            rolls = GRID_ROLLS.get(c, 1)
            for k in range(rolls):
                notes.append([start + k * row_step / rolls, row_step / rolls, row, vel * velocity * (0.85 if k else 1.0), dict(opts)])
    notes.sort(key=lambda n: n[0])
    return notes, total


# ----------------------------------------------------------------------------------------------------- instruments

def gm_number(name):
    """'violin' / 'скрипка' / '40' → General MIDI program (ignores live SFZ presets)."""
    from . import engine
    low = str(name).strip().lower()
    if low.isdigit():
        return int(low)
    key = low.replace('_', ' ').replace('-', ' ')
    if key in ALIAS_TO_GM:
        return ALIAS_TO_GM[key]
    hits = [i for i, n in enumerate(engine.GM_NAMES) if all(w in n.lower() for w in key.split())]
    if not hits:
        raise NotationError(f'нет GM-инструмента {name!r}')
    return hits[0]


def resolve_instrument(inst):
    """String or dict → instrument dict the engine understands."""
    from . import engine, samples
    if inst is None:
        inst = 'piano'                                        # живое пианино (Salamander), не синт
    if isinstance(inst, dict):
        out = dict(inst)
        if isinstance(out.get('real'), str):
            out.update(resolve_instrument('real:' + out.pop('real')))
        if isinstance(out.get('gm'), str):
            out['gm'] = gm_number(out['gm'])
        if 'noteblock' in out:
            nb = out.pop('noteblock')
            out['sample'] = f'mc:note_block/{nb}'
        if 'sample' in out and 'root' not in out:
            root = samples.default_root(out['sample'])
            if root:
                out['root'] = root
        return out
    if isinstance(inst, (int, float)):
        return {'gm': int(inst)}
    s = str(inst).strip()
    low = s.lower()
    if low in VOICE_WORDS:
        return dict(VOICE_WORDS[low])
    if low.startswith('real:') or low.startswith('sfz:') or low.startswith('sso:'):
        from . import sfz
        name = s.split(':', 1)[1] if not low.startswith('sso:') else s
        p = sfz.preset(name) if not low.startswith('sso:') else None
        try:
            p = p or sfz.find(name)
        except sfz.SfzError as exc:
            raise NotationError(str(exc)) from None
        return {'sfz': str(p)}
    for prefix in ('synth:', 'gm:', 'kit:', 'noteblock:', 'nb:', 'sample:'):
        if low.startswith(prefix):
            v = s[len(prefix):]
            if prefix == 'synth:':
                return {'synth': v}
            if prefix == 'kit:':
                return {'kit': v}
            if prefix in ('noteblock:', 'nb:'):
                return resolve_instrument({'sample': f'mc:note_block/{v}'})
            if prefix == 'sample:':
                return resolve_instrument({'sample': v})
            return resolve_instrument({'gm': int(v) if v.isdigit() else v})
    if low.startswith(('mc:', 'samples:', 'library:')):
        return resolve_instrument({'sample': s})
    if low in DRUM_WORDS:
        return {'gm_drums': True}
    if low.isdigit():
        return {'gm': int(low)}
    key = low.replace('_', ' ').replace('-', ' ')
    from . import sfz
    real = sfz.preset(low) or sfz.preset(key)
    if real:                                                     # живые записи важнее GM, если библиотека установлена
        return {'sfz': str(real)}
    if key in ALIAS_TO_GM or low in ALIAS_TO_GM:
        return {'gm': ALIAS_TO_GM.get(key, ALIAS_TO_GM.get(low))}
    if low in SYNTH_ALIASES:
        return {'synth': SYNTH_ALIASES[low]}
    if low in engine.SYNTHS:
        return {'synth': low}
    words = key.split()
    hits = [i for i, n in enumerate(engine.GM_NAMES) if all(w in n.lower() for w in words)]
    if hits:
        return {'gm': hits[0]}
    raise NotationError(f'не знаю инструмент {inst!r}. Примеры: piano, violin/скрипка, guitar, distortion guitar, '
                        f'bass guitar, flute, choir, drums, synth:musicbox, noteblock:harp, mc:<звук>')


# ----------------------------------------------------------------------------------------------------- expansion

def _content(spec, track, key, beats_per_bar, rng):
    """One piece of content (string / list / dict) → (notes, length in beats | None)."""
    opt = {**{k: track[k] for k in track if k in CONTENT_OPTS}, **(spec if isinstance(spec, dict) else {})}
    notes, length = [], 0.0
    if isinstance(spec, str):
        spec = {'melody': spec}
    elif isinstance(spec, list):
        spec = {'notes': spec}
    if 'melody' in spec or isinstance(spec.get('notes'), str):
        n, ln = parse_melody(spec.get('melody', spec.get('notes')), opt.get('length', 1.0), opt.get('velocity', 0.8),
                             opt.get('octave', 4), key)
        notes += n
        length = max(length, ln)
    elif isinstance(spec.get('notes'), list):
        n = [list(x) for x in spec['notes']]
        notes += n
        end = max((x[0] + x[1] for x in n), default=0)
        length = max(length, math.ceil(end / beats_per_bar - 1e-6) * beats_per_bar if end else 0)
    if 'chords' in spec:
        n, ln = parse_chords(spec['chords'], opt.get('style', 'block'), opt.get('chord_octave', opt.get('octave', 3)),
                             opt.get('chord_length', beats_per_bar), opt.get('velocity', 0.7), key,
                             opt.get('arp_step', 0.5), opt.get('pulse', 1.0), opt.get('strum', 0.04),
                             opt.get('bass', False), opt.get('gate', 0.95))
        notes += n
        length = max(length, ln)
    if 'drums' in spec:
        n, ln = parse_grid(spec['drums'], opt.get('step', 0.25), opt.get('swing', 0.0), opt.get('velocity', 1.0))
        notes += n
        length = max(length, ln)
    if spec.get('length_beats'):
        length = float(spec['length_beats'])
    elif spec.get('bars'):
        length = float(spec['bars']) * beats_per_bar
    if opt.get('lyrics') and 'drums' not in spec:
        from .voice_extra import singable
        syl = singable(opt['lyrics'], opt.get('lang', 'auto')) or ['а']
        k, last = -1, None
        for x in sorted(notes, key=lambda n: n[0]):
            if last is None or abs(x[0] - last) > 1e-6:
                k += 1
            last = x[0]
            while len(x) < 4:
                x.append(0.8)
            if len(x) == 4:
                x.append({})
            x[4] = {**x[4], 'syl': syl[k % len(syl)]}
    gate = opt.get('gate')
    if gate and 'drums' not in spec and 'chords' not in spec:
        for x in notes:
            x[1] *= gate
    hum = opt.get('humanize')
    if hum:
        ht = hum.get('time', 0.01) if isinstance(hum, dict) else 0.01 * float(hum)
        hv = hum.get('vel', 0.08) if isinstance(hum, dict) else 0.08 * float(hum)
        for x in notes:
            x[0] = max(0.0, x[0] + rng.uniform(-ht, ht))
            if len(x) > 3:
                x[3] = min(1.0, max(0.05, x[3] + rng.uniform(-hv, hv)))
    return notes, length


CONTENT_OPTS = {'length', 'velocity', 'octave', 'style', 'chord_octave', 'chord_length', 'arp_step', 'pulse', 'strum',
                'bass', 'gate', 'step', 'swing', 'humanize', 'lyrics', 'lang'}
VOICE_WORDS = {
    # настоящее пение нейросетью SoulX-Singer (поёт ноты точно)
    'voice': {'singer': 'en_female'}, 'голос': {'singer': 'en_female'}, 'вокал': {'singer': 'en_female'},
    'singer': {'singer': 'en_female'}, 'певица': {'singer': 'en_female'}, 'vocal': {'singer': 'en_female'},
    'вокалистка': {'singer': 'en_female'}, 'real voice': {'singer': 'en_female'}, 'настоящий голос': {'singer': 'en_female'},
    'singer zh': {'singer': 'zh_female'}, 'певица 2': {'singer': 'zh_female'},
    'singers': {'singer': 'en_female', 'takes': 4}, 'певицы': {'singer': 'en_female', 'takes': 4},
    'vocal choir': {'singer': 'en_female', 'takes': 6}, 'хор певиц': {'singer': 'en_female', 'takes': 6},
    # старый голос из синтеза речи Windows (роботизированный; для SFX, шёпота, мимиков)
    'tts voice': {'voice': 'auto'}, 'ттс голос': {'voice': 'auto'}, 'робо-голос': {'voice': 'auto'},
    'choir voices': {'singer': 'en_female', 'takes': 6}, 'voice choir': {'singer': 'en_female', 'takes': 6},
    'хор голосов': {'singer': 'en_female', 'takes': 6}, 'поющий хор': {'singer': 'en_female', 'takes': 6},
    'mixed voices': {'singer': 'en_female', 'takes': 6}, 'смешанный хор': {'singer': 'en_female', 'takes': 6},
    'male voice': {'singer': 'zh_male'}, 'мужской голос': {'singer': 'zh_male'}, 'певец': {'singer': 'zh_male'},
    'male choir': {'singer': 'zh_male', 'takes': 5}, 'мужской хор': {'singer': 'zh_male', 'takes': 5},
    'child voice': {'voice': 'auto', 'formant': 1.18}, 'детский голос': {'voice': 'auto', 'formant': 1.18},
    'anime voice': {'singer': 'en_female'}, 'аниме голос': {'singer': 'en_female'},
    'vocal chops': {'singer': 'en_female'}, 'вокальные чопы': {'singer': 'en_female'},
    'angel voices': {'singer': 'en_female', 'takes': 6}, 'ангельские голоса': {'singer': 'en_female', 'takes': 6},
    'children choir': {'singer': 'en_female', 'takes': 5}, 'детский хор': {'singer': 'en_female', 'takes': 5},
    'tts choir': {'voice': 'irina', 'voices': 10, 'formant': 1.1, 'vibrato': 18, 'breath': 0.18, 'spread': 0.8},
}
# Track presets: "preset": "<name>" fills instrument/effects/options (the track's own fields win; effects are appended).
TRACK_PRESETS = {
    'angel choir': {'instrument': {'layers': ['angel voices', {'instrument': 'real:large choir', 'gain': 0.55}]},
                    'lyrics': 'а', 'effects': [{'type': 'shimmer', 'size': 1.2, 'mix': 0.5}]},
    'ангельский хор': '=angel choir',
    'abyss chant': {'instrument': {'singer': 'en_female', 'takes': 2}, 'lyrics': 'ха не зэ вэ ка ра ди на', 'vibrato': 18,
                    'effects': [{'type': 'reverb', 'size': 1.1, 'mix': 0.35}, {'type': 'delay', 'time': '3/8', 'feedback': 0.25, 'mix': 0.15}]},
    'anime vocal': {'instrument': {'singer': 'en_female'}, 'lang': 'ja',
                    'effects': [{'type': 'eq', 'high': 3, 'high_freq': 5000}, {'type': 'reverb', 'size': 0.6, 'mix': 0.22}]},
    'аниме вокал': '=anime vocal',
    'jumping voices': {'instrument': 'vocal chops', 'lyrics': 'а я о э хэй у я', 'gate': 0.7,
                       'effects': [{'type': 'delay', 'time': '3/16', 'feedback': 0.3, 'mix': 0.2, 'pingpong': True},
                                   {'type': 'reverb', 'size': 0.5, 'mix': 0.2}]},
    'вокальные чопы': '=jumping voices',
}


def apply_preset(track):
    name = track.get('preset')
    if not name:
        return track
    p = TRACK_PRESETS.get(str(name).lower())
    while isinstance(p, str) and p.startswith('='):
        p = TRACK_PRESETS.get(p[1:])
    if p is None:
        raise NotationError(f'нет пресета дорожки {name!r}; есть: {", ".join(k for k in TRACK_PRESETS if not isinstance(TRACK_PRESETS[k], str))}')
    out = {**copy.deepcopy(p), **{k: v for k, v in track.items() if k != 'preset'}}
    out['effects'] = copy.deepcopy(p.get('effects', [])) + list(track.get('effects', []))
    return out
CONTENT_KEYS = ('notes', 'melody', 'chords', 'drums')


def _place(notes, length, start, span, loop):
    """Put pattern notes at `start`, looping to fill `span` beats (None = once)."""
    out = []
    if not loop or not length or span is None:
        reps = 1
    else:
        reps = max(1, math.ceil(span / length - 1e-6))
    for r in range(reps):
        for n in notes:
            s = n[0] + r * length
            if span is not None and s >= span - 1e-6:
                continue
            m = list(n)
            m[0] = s + start
            if span is not None and s + m[1] > span and loop:
                m[1] = span - s
            out.append(m)
    return out


def sections_layout(recipe):
    """[(name, start_beat, length_beats)] from recipe['sections'] + recipe['arrange']."""
    arrange = recipe.get('arrange')
    if not arrange:
        return []
    if isinstance(arrange, str):
        arrange = arrange.split()
    bpb = float(recipe.get('beats_per_bar', 4))
    secs = recipe.get('sections', {})
    out, t = [], 0.0
    for item in arrange:
        name, _, times = str(item).partition('*')
        for _ in range(int(times or 1)):
            s = secs.get(name, {})
            if isinstance(s, (int, float)):
                length = float(s) * bpb
            else:
                length = float(s.get('beats') or s.get('bars', recipe.get('bars_per_section', 4)) * bpb)
            out.append((name, t, length))
            t += length
    return out


def has_compact(track):
    return bool(track.get('parts') or any(k in track for k in ('melody', 'chords', 'drums'))
                or isinstance(track.get('notes'), str) or isinstance(track.get('instrument'), (str, int))
                or track.get('loop') and track.get('type', 'notes') == 'notes' or track.get('sections')
                or track.get('transpose'))


def expand_track(track, recipe, index=0, layout=None):
    """One track in compact form → explicit form. Returns a list (sfx/audio tracks placed in sections may multiply)."""
    layout = sections_layout(recipe) if layout is None else layout
    kind = track.get('type', 'notes')
    key = track.get('key', recipe.get('key'))
    bpb = float(recipe.get('beats_per_bar', 4))
    rng = random.Random(f'{recipe.get("seed", 0)}:{index}:{track.get("name", "")}')
    track = apply_preset(track)
    t = copy.deepcopy(track)
    in_secs = t.pop('sections', None)
    if isinstance(in_secs, str):
        in_secs = in_secs.split()
    if kind != 'notes':
        if not in_secs:
            return [t]
        out = []
        for name, start, _ in layout:
            if name in in_secs:
                c = copy.deepcopy(t)
                c['at'] = start + float(t.get('at', 0))
                out.append(c)
        return out
    inst = t.get('instrument')
    if 'drums' in t or any(isinstance(p, dict) and 'drums' in p for p in (t.get('parts') or {}).values()):
        if inst is None or (isinstance(inst, str) and inst.lower() in DRUM_WORDS | {'synth', 'gm', '808', 'mc'}):
            kit = t.pop('kit', None) or (inst if isinstance(inst, str) and inst.lower() in ('synth', 'gm', '808', 'mc') else
                                         'gm' if isinstance(inst, str) else 'synth')
            t['instrument'] = {'kit': kit}
    if 'kit' in t:
        t['instrument'] = {'kit': t.pop('kit')}
    t['instrument'] = resolve_instrument(t.get('instrument'))
    notes = []
    parts = t.pop('parts', None)
    own = {k: t.pop(k) for k in CONTENT_KEYS if k in t}
    loop = t.pop('loop', None)
    if parts:
        for name, start, span in layout:
            spec = parts.get(name)
            if isinstance(spec, str) and spec.startswith('='):
                spec = parts.get(spec[1:])
            if spec is None:
                continue
            n, ln = _content(spec, track, key, bpb, rng)
            notes += _place(n, ln, start, span, not (isinstance(spec, dict) and spec.get('loop') is False))
    if own:
        n, ln = _content(own, track, key, bpb, rng)
        if in_secs:
            for name, start, span in layout:
                if name in in_secs:
                    notes += _place(n, ln, start, span, loop is not False)
        elif isinstance(loop, (int, float)) and not isinstance(loop, bool) and loop > 1:
            notes += _place(n, ln, 0, ln * int(loop), True)
        elif loop is True and (recipe.get('length_beats') or layout):
            total = recipe.get('length_beats') or (layout[-1][1] + layout[-1][2])
            notes += _place(n, ln, 0, float(total), True)
        else:
            notes += n
    tr = float(t.pop('transpose', 0)) + float(recipe.get('transpose', 0))
    if tr and not t['instrument'].get('kit') and not t['instrument'].get('gm_drums'):
        for n in notes:
            if isinstance(n[2], (int, float)):
                n[2] = n[2] + tr
            elif re.fullmatch(r'[A-Ga-g](##|#|bb|b|s)?-?\d', str(n[2])):
                n[2] = note_number(str(n[2]), 4)[0] + tr
    for opt in CONTENT_OPTS | {'key'}:
        t.pop(opt, None)
    notes.sort(key=lambda n: n[0])
    t['notes'] = [[round(n[0], 5), round(n[1], 5)] + list(n[2:]) for n in notes]
    layers = t['instrument'].get('layers')
    if layers:                                            # один голос на нескольких инструментах сразу (скрипка + хор)
        out = []
        for k, layer in enumerate(layers):
            c = copy.deepcopy(t)
            spec = layer.get('instrument', layer) if isinstance(layer, dict) and 'instrument' in layer else layer
            c['instrument'] = resolve_instrument(spec)
            c['gain'] = float(t.get('gain', 0.8)) * float(layer.get('gain', 1.0) if isinstance(layer, dict) else 1.0)
            if isinstance(layer, dict) and layer.get('transpose'):
                c['notes'] = [[n[0], n[1], note_number(str(n[2]), 4)[0] + float(layer['transpose'])] + list(n[3:])
                              if not isinstance(n[2], (int, float)) else [n[0], n[1], n[2] + float(layer['transpose'])] + list(n[3:])
                              for n in c['notes']]
            c['name'] = f'{t.get("name", "track")}' + ('' if k == 0 else f' +{k}')
            out.append(c)
        return out
    return [t]


def expand_recipe(recipe):
    """Compact recipe → explicit recipe (deep copy). Adds `_sections` with the layout for UIs."""
    r = copy.deepcopy(recipe)
    layout = sections_layout(r)
    tracks = []
    for i, tr in enumerate(r.get('tracks', [])):
        tracks += expand_track(tr, r, i, layout)
    r['tracks'] = tracks
    if layout:
        r['_sections'] = [{'name': n, 'at': s, 'beats': ln} for n, s, ln in layout]
        r.setdefault('sections_markers', [{'at': s, 'name': n} for n, s, _ in layout])
    for k in ('arrange',):
        r.pop(k, None)
    return r
