"""Composers that *write recipes*: calm lullabies in the spirit of C418, horror ambience, and a «morph» that turns
one into the other on a chosen beat. The result is an ordinary recipe — open it in the web app and edit notes,
instruments and effects by hand."""
import copy
import random

SCALES = {
    'major': [0, 2, 4, 5, 7, 9, 11],
    'lydian': [0, 2, 4, 6, 7, 9, 11],
    'dorian': [0, 2, 3, 5, 7, 9, 10],
    'minor': [0, 2, 3, 5, 7, 8, 10],
    'phrygian': [0, 1, 3, 5, 7, 8, 10],
}
KEYS = {'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3, 'E': 4, 'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8,
        'Ab': 8, 'A': 9, 'A#': 10, 'Bb': 10, 'B': 11}
PROGRESSIONS = [[4, 1, 5, 6], [1, 6, 4, 5], [6, 4, 1, 5], [1, 3, 4, 4], [4, 5, 3, 6], [1, 5, 6, 4]]


def degree_note(key, scale, degree, octave):
    """Scale degree (1-based, may exceed 7) → MIDI number."""
    s = SCALES[scale]
    d = degree - 1
    return 12 * (octave + 1) + KEYS[key] + s[d % 7] + 12 * (d // 7)


def chord(key, scale, root_degree, octave, size=4):
    return [degree_note(key, scale, root_degree + 2 * i, octave) for i in range(size)]


def calm(key='F', scale='lydian', tempo=72, bars=8, seed=1, lead='musicbox', name='calm'):
    """Gentle, sparse piece: pad chords, broken piano chords, a music-box motif that repeats with variations."""
    rnd = random.Random(seed)
    prog = rnd.choice(PROGRESSIONS)
    pad, piano, melody, bass = [], [], [], []
    motif = None
    for bar in range(bars):
        deg = prog[bar % len(prog)]
        t0 = bar * 4
        ch = chord(key, scale, deg, 3)
        for n in ch[:3]:
            pad.append([t0, 4.2, n, 0.45])
        bass.append([t0, 3.5, ch[0] - 12, 0.55])
        # ломаный аккорд пианино
        rhythm = rnd.choice([[0, 1.5, 3], [0, 1, 2, 3], [0.5, 2, 2.5], [0, 2]])
        up = chord(key, scale, deg, 4, 5)
        for i, r in enumerate(rhythm):
            piano.append([t0 + r, 1.5, up[(i * 2) % len(up)], 0.35 + rnd.random() * 0.15])
        # мотив шкатулки: 2 такта мотив, 2 такта вариация
        if bar % 4 == 0 or motif is None:
            motif = []
            beat = 0.0
            while beat < 4:
                length = rnd.choice([0.5, 1, 1, 1.5, 2])
                step = rnd.choice([0, 2, 4, 5, 7, 9])
                motif.append([beat, length, step])
                beat += length
        for b, length, step in motif:
            if rnd.random() < 0.18:
                continue                                  # паузы — «воздух» как у C418
            varied = step + (rnd.choice([-1, 1, 2]) if bar % 2 == 1 and rnd.random() < 0.4 else 0)
            melody.append([t0 + b, length, degree_note(key, scale, deg + varied, 5), 0.55 + rnd.random() * 0.2])
    lead_inst = {'synth': lead} if lead in ('musicbox', 'bell', 'epiano', 'pluck', 'piano') else {'gm': int(lead)}
    return {
        'name': name, 'kind': 'music', 'tags': ['calm', 'c418'], 'tempo': tempo, 'seed': seed,
        'description': f'спокойная пьеса: {key} {scale}, {bars} тактов, прогрессия {prog}',
        'tracks': [
            {'name': 'пэд', 'type': 'notes', 'instrument': {'synth': 'pad', 'params': {'attack': 1.5, 'release': 3, 'cutoff': 1400}},
             'notes': pad, 'gain': 0.35, 'effects': [{'type': 'reverb', 'size': 0.8, 'mix': 0.4}]},
            {'name': 'пианино', 'type': 'notes', 'instrument': 'piano', 'notes': piano, 'gain': 0.6, 'pan': -0.15,
             'effects': [{'type': 'reverb', 'size': 0.7, 'mix': 0.35}]},
            {'name': 'шкатулка', 'type': 'notes', 'instrument': lead_inst, 'notes': melody, 'gain': 0.7, 'pan': 0.2,
             'effects': [{'type': 'delay', 'time': '3/16', 'feedback': 0.3, 'mix': 0.2}, {'type': 'reverb', 'size': 0.8, 'mix': 0.4}]},
            {'name': 'бас', 'type': 'notes', 'instrument': {'synth': 'bass'}, 'notes': bass, 'gain': 0.35},
        ],
        'master': {'normalize': -2.0},
    }


def horror(key='C', tempo=72, bars=8, intensity=0.7, seed=2, name='dread'):
    """Dark ambience: drone, detuned string swells, low piano clusters, heartbeat that speeds up, whispers, screech."""
    rnd = random.Random(seed)
    beats = bars * 4
    root = 12 * 3 + KEYS[key]
    strings, piano = [], []
    for bar in range(0, bars, 2):
        cluster = [root, root + 1, root + 6, root + 13] if rnd.random() < intensity else [root, root + 3, root + 6]
        for n in cluster:
            strings.append([bar * 4, 8, n, 0.5])
    for i in range(int(bars * (1 + 2 * intensity))):
        t = rnd.uniform(0, beats - 1)
        low = root - 12 + rnd.choice([0, 1, 6, 7])
        for n in (low, low + 1, low + 6):
            piano.append([round(t * 2) / 2, 2, n, 0.5 + 0.4 * rnd.random()])
    tracks = [
        {'name': 'гул', 'type': 'sfx', 'sfx': 'drone', 'at': 0, 'duration_beats': beats,
         'params': {'pitch': 440 * 2 ** ((root - 12 - 69) / 12), 'brightness': 0.6 + intensity * 0.6}, 'gain': 0.8},
        {'name': 'струнные', 'type': 'notes', 'instrument': {'gm': 49}, 'notes': strings, 'gain': 0.5,
         'automation': {'detune': [[0, 0], [beats, -60 * intensity]]},
         'effects': [{'type': 'reverb', 'size': 0.9, 'mix': 0.5}]},
        {'name': 'низкое пианино', 'type': 'notes', 'instrument': {'gm': 0}, 'notes': piano, 'gain': 0.55,
         'effects': [{'type': 'reverb', 'size': 0.9, 'mix': 0.45}]},
        {'name': 'сердце', 'type': 'sfx', 'sfx': 'heartbeat', 'at': beats * 0.25,
         'params': {'bpm': 60 + 60 * intensity, 'beats': int(beats * 0.6)}, 'gain': 0.7},
        {'name': 'шёпот', 'type': 'sfx', 'sfx': 'whisper', 'at': beats * 0.3, 'params': {'duration': beats * 60 / tempo * 0.5},
         'gain': 0.35, 'pan': -0.6, 'effects': [{'type': 'reverb', 'size': 0.5, 'mix': 0.3}]},
    ]
    if intensity > 0.5:
        tracks.append({'name': 'скрежет', 'type': 'sfx', 'sfx': 'screech', 'at': beats * 0.7, 'params': {'duration': 3.0},
                       'gain': 0.45, 'pan': 0.5, 'effects': [{'type': 'reverb', 'size': 0.8, 'mix': 0.4}]})
    return {'name': name, 'kind': 'music', 'tags': ['horror'], 'tempo': tempo, 'seed': seed,
            'description': f'хоррор-эмбиент: {key}, {bars} тактов, интенсивность {intensity}',
            'tracks': tracks, 'master': {'normalize': -2.0, 'effects': [{'type': 'compress', 'threshold': -20}]}}


def morph(calm_recipe, horror_recipe, at_beat=32, style='melt', transition=4, name='calm_to_horror'):
    """Glue two recipes: the calm one plays, then on `at_beat` it turns into the horror one.

    style: «cut» — резко в долю, со скример-аккордом; «melt» — мелодия «плывёт» вниз, фильтр закрывается, затем
    хоррор; «fade» — плавный кроссфейд за transition долей.
    """
    calm_r = copy.deepcopy(calm_recipe)
    hor = copy.deepcopy(horror_recipe)
    start = at_beat - (transition if style != 'cut' else 0)
    tracks = []
    for tr in calm_r['tracks']:
        auto = tr.setdefault('automation', {})
        if style == 'melt':
            auto['detune'] = [[0, 0], [start, 0], [at_beat, -150]]
            auto['lowpass'] = [[0, 18000], [start, 18000], [at_beat, 300]]
            auto['gain'] = [[0, 1], [start, 1], [at_beat + 1, 0]]
        elif style == 'fade':
            auto['gain'] = [[0, 1], [start, 1], [at_beat, 0]]
        else:
            auto['gain'] = [[0, 1], [at_beat - 0.02, 1], [at_beat, 0]]
        tr['notes'] = [n for n in tr.get('notes', []) if n[0] < at_beat + 1] if tr.get('type', 'notes') == 'notes' else tr.get('notes')
        tr['name'] = 'хорошо: ' + tr.get('name', '')
        tracks.append(tr)
    for tr in hor['tracks']:
        if tr.get('type', 'notes') == 'notes':
            tr['notes'] = [[n[0] + at_beat] + list(n[1:]) for n in tr.get('notes', [])]
            auto = tr.get('automation', {})
            for k, pts in auto.items():
                auto[k] = [[p[0] + at_beat, p[1]] for p in pts]
        else:
            tr['at'] = float(tr.get('at', 0)) + at_beat
        if style == 'fade':
            tr.setdefault('automation', {})['gain'] = [[0, 0], [start, 0], [at_beat + transition, 1]]
        tr['gain'] = float(tr.get('gain', 0.8)) * 0.6                 # хоррор не должен заглушать начало
        tr['name'] = 'жуть: ' + tr.get('name', '')
        tracks.append(tr)
    if style != 'fade':
        tracks.append({'name': 'нарастание', 'type': 'sfx', 'sfx': 'riser', 'at': max(0, at_beat - transition),
                       'params': {'duration': transition * 60 / calm_r.get('tempo', 72)}, 'gain': 0.5})
        tracks.append({'name': 'удар', 'type': 'sfx', 'sfx': 'sting' if style == 'cut' else 'impact', 'at': at_beat, 'gain': 0.8})
    return {'name': name, 'kind': 'music', 'tags': ['morph', 'calm', 'horror'], 'tempo': calm_r.get('tempo', 72),
            'description': f'хорошая галлюцинация → хоррор на доле {at_beat} ({style})', 'tracks': tracks,
            'sections': [{'at': 0, 'name': 'хорошо'}, {'at': at_beat, 'name': 'жуть'}],
            'master': {'normalize': -1.5}}


# ----------------------------------------------------------------------------------------------------- beats

NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def _name(midi):
    return f'{NAMES[midi % 12]}{midi // 12 - 1}'


BEAT_STYLES = {
    'lofi': {'tempo': 82, 'key': 'A minor', 'kit': 'synth', 'swing': 0.12,
             'drums': {'kick': 'x.....x...x.....', 'snare': '....x.......x..g', 'hat': 'x.x.x.x.x.x.x.xo'},
             'chords': 'i7 iv7 VImaj7 v7', 'keys': 'electric piano', 'style': 'block', 'bass': 'acoustic bass',
             'lead': 'vibraphone', 'master': [{'type': 'lofi', 'wow': 0.6}, {'type': 'compress', 'threshold': -16}]},
    'trap': {'tempo': 140, 'key': 'F minor', 'kit': '808', 'swing': 0.0,
             'drums': {'kick': 'x......x..x.....', 'snare': '........x.......', 'hat': 'x.x.xrx.x.x.t.x.',
                       'ohat': '..............x.'},
             'chords': 'i VI iv V', 'keys': 'strings', 'style': 'block', 'bass': '808', 'lead': 'synth:bell',
             'master': [{'type': 'compress', 'threshold': -14}]},
    'house': {'tempo': 124, 'key': 'C minor', 'kit': 'synth', 'swing': 0.05,
              'drums': {'kick': 'x...x...x...x...', 'clap': '....x.......x...', 'ohat': '..x...x...x...x.',
                        'hat': 'xxxxxxxxxxxxxxxx'},
              'chords': 'i7 VImaj7 III VII', 'keys': 'synth:pad', 'style': 'pulse', 'bass': 'synth bass',
              'lead': 'synth:pluck', 'master': [{'type': 'compress', 'threshold': -14}]},
    'rock': {'tempo': 120, 'key': 'E minor', 'kit': 'gm', 'swing': 0.0,
             'drums': {'kick': 'x.....x.x.......', 'snare': '....x.......x...', 'hat': 'x.x.x.x.x.x.x.x.',
                       'crash': 'x...............'},
             'chords': 'i VI III VII', 'keys': 'distortion guitar', 'style': 'root_fifth', 'bass': 'pick bass',
             'lead': 'overdriven guitar', 'master': [{'type': 'compress', 'threshold': -16}]},
    'chiptune': {'tempo': 150, 'key': 'C major', 'kit': 'synth', 'swing': 0.0,
                 'drums': {'kick': 'x...x...x...x...', 'snare': '....x.......x...', 'hat': 'x.x.x.x.x.x.x.x.'},
                 'chords': 'I V vi IV', 'keys': 'synth:triangle', 'style': 'arp', 'bass': 'synth:square',
                 'lead': 'synth:square', 'master': [{'type': 'bitcrush', 'bits': 8, 'downsample': 2}]},
    'noteblock': {'tempo': 120, 'key': 'F# major', 'kit': 'mc', 'swing': 0.0,
                  'drums': {'kick': 'x...x...x...x...', 'snare': '....x.......x...', 'hat': '..x...x...x...x.'},
                  'chords': 'I vi IV V', 'keys': 'noteblock:harp', 'style': 'arp', 'bass': 'noteblock:bass',
                  'lead': 'noteblock:bell', 'master': []},
}


def _melody(tonic_name, mode, bars, rnd, octave=5):
    """Stepwise melody on the scale as a notation string (bar lines included)."""
    from .notation import MODES, parse_key
    tonic, mode = parse_key(f'{tonic_name} {mode}')
    scale = MODES[mode]
    rhythms = [[1, 1, 1, 1], [1.5, 0.5, 1, 1], [0.5, 0.5, 1, 2], [1, 0.5, 0.5, 2], [2, 1, 1], [0.5, 0.5, 0.5, 0.5, 2]]
    deg = rnd.choice([0, 2, 4])
    out = []
    for bar in range(bars):
        rhythm = rnd.choice(rhythms)
        cells = []
        for i, d in enumerate(rhythm):
            if rnd.random() < 0.12 and i:
                cells.append(f'r:{d:g}')
                continue
            deg = max(-2, min(9, deg + rnd.choice([-2, -1, -1, 1, 1, 2, 0, 3])))
            if bar == bars - 1 and i == len(rhythm) - 1:
                deg = 0
            midi = 12 * (octave + 1) + tonic + scale[deg % 7] + 12 * (deg // 7)
            cells.append(f'{_name(midi)}:{d:g}')
        out.append(' '.join(cells))
    return ' | '.join(out)


def beat(style='lofi', tempo=None, key=None, bars=4, seed=1, name=None, lead=True):
    """A starter beat in a style: drums grid + chords + bass + (optional) lead, sections intro/main/drop.
    The recipe uses compact notation — edit patterns, chords and instruments afterwards."""
    from .notation import parse_key, NOTE_BASE
    if style not in BEAT_STYLES:
        raise ValueError(f'стиль: {", ".join(BEAT_STYLES)}')
    s = BEAT_STYLES[style]
    rnd = random.Random(seed)
    tonic_pc, mode = parse_key(key or s['key'])
    tonic = NAMES[tonic_pc]
    full_key = f'{tonic} {mode}'
    drums_main = dict(s['drums'])
    drums_intro = {k: v for k, v in drums_main.items() if k in ('hat', 'kick')}
    fx_keys = [{'type': 'reverb', 'size': 0.5, 'mix': 0.2}]
    if style in ('house', 'trap'):
        fx_keys.append({'type': 'sidechain', 'every': 1, 'depth': 0.6})
    tracks = [
        {'name': 'ударные', 'kit': s['kit'], 'swing': s['swing'], 'gain': 0.9,
         'parts': {'intro': {'drums': drums_intro}, 'main': {'drums': drums_main}, 'drop': {'drums': drums_main}}},
        {'name': 'аккорды', 'instrument': s['keys'], 'chords': s['chords'], 'style': s['style'], 'chord_octave': 4,
         'pulse': 0.5 if style == 'house' else 1, 'arp_step': 0.25 if style in ('chiptune', 'noteblock') else 0.5,
         'loop': True, 'gain': 0.5, 'effects': fx_keys},
    ]
    if s['bass'] == '808':
        tracks.append({'name': '808', 'instrument': {'synth': 'sine', 'params': {'release': 0.4}},
                       'chords': s['chords'], 'style': 'root', 'pulse': 2, 'chord_octave': 2, 'sections': 'main drop',
                       'gain': 0.8, 'effects': [{'type': 'distortion', 'drive': 2, 'mix': 0.4}]})
    else:
        bass_style = {'house': 'root_octave', 'chiptune': 'root_octave', 'rock': 'root_fifth'}.get(style, 'root')
        tracks.append({'name': 'бас', 'instrument': s['bass'], 'chords': s['chords'], 'style': bass_style,
                       'pulse': 0.5 if style in ('house', 'chiptune', 'rock') else 1, 'chord_octave': 3,
                       'sections': 'main drop', 'gain': 0.45 if style == 'noteblock' else 0.7})
    if lead:
        tracks.append({'name': 'мелодия', 'instrument': s['lead'], 'parts': {'drop': _melody(tonic, mode, bars, rnd)},
                       'gain': 0.6, 'effects': [{'type': 'delay', 'time': '3/16', 'feedback': 0.3, 'mix': 0.2}]})
    return {'name': name or f'{style}_beat', 'kind': 'music', 'tags': ['beat', style], 'tempo': tempo or s['tempo'],
            'key': full_key, 'seed': seed, 'description': f'бит {style}: {full_key}, аккорды {s["chords"]}',
            'sections': {'intro': {'bars': 2}, 'main': {'bars': bars}, 'drop': {'bars': bars}},
            'arrange': 'intro main drop main drop', 'tracks': tracks,
            'master': {'normalize': -1, 'effects': s['master'], 'fade_out': 1.5}}


# ----------------------------------------------------------------------------------------------------- songs

SONG_STYLES = {
    'abyss': {'tempo': 70, 'key': 'D minor', 'verse': 'i VI III VII', 'chorus': 'VI VII i i',
              'lyrics': 'ха не зэ вэ ка ра ди на лэ а ну ми рэ о на си э ку ра ми',
              'desc': 'эфирная сказка: челеста, арфа, струнные, детский голос на выдуманном языке, ангельский хор'},
    'takopi': {'tempo': 86, 'key': 'D major', 'verse': 'I vi IV V', 'chorus': 'IV V iii vi',
               'lyrics': 'ら ら る な の ま み ゆ め そ ら あ お う き み た こ ね',
               'desc': 'нежная аниме-песня: гитара, рояль, глокеншпиль, мягкие барабаны, аниме-вокал по-японски'},
    'jumping': {'tempo': 126, 'key': 'F major', 'verse': 'I V vi IV', 'chorus': 'IV V vi I',
                'lyrics': 'а я о э хэй у я а',
                'desc': 'бодрая: прыгающие вокальные чопы, плаки, бочка в пол, бас'},
    'angelic': {'tempo': 58, 'key': 'C major', 'verse': 'I vi IV V', 'chorus': 'IV V iii vi ii V I I',
                'lyrics': 'а-ле-лу-я',
                'desc': 'ангельский гимн: хор голосов + живой хор с шиммером, орган, арфа, струнные'},
}


def _phrase(tonic, mode, bars, rnd, octave, rhythms, leap):
    """A singable phrase: stepwise with occasional leaps, ends on a chord tone."""
    from .notation import MODES, parse_key
    tpc, mode = parse_key(f'{tonic} {mode}')
    scale = MODES[mode]
    deg = rnd.choice([0, 2, 4])
    bars_out = []
    for bar in range(bars):
        cells = []
        for i, d in enumerate(rnd.choice(rhythms)):
            step = rnd.choice([-1, -1, 1, 1, 2, -2, 0]) if rnd.random() > leap else rnd.choice([3, 4, -3, 5, -4])
            deg = max(-2, min(9, deg + step))
            if bar == bars - 1 and i == 0:
                deg = rnd.choice([0, 2, 4])
            midi = 12 * (octave + 1) + tpc + scale[deg % 7] + 12 * (deg // 7)
            cells.append(f'{_name(midi)}:{d:g}')
        bars_out.append(' '.join(cells))
    return bars_out


def _tune(tonic, mode, bars, rnd, octave, rhythms, leap=0.15):
    """Song melody with repetition (A A' form): phrase, answer, phrase again, answer resolving home."""
    half = max(1, bars // 2)
    a = _phrase(tonic, mode, half, rnd, octave, rhythms, leap)
    b = _phrase(tonic, mode, half, rnd, octave, rhythms, leap)
    tail = _phrase(tonic, mode, 1, random.Random(rnd.random()), octave, rhythms, 0)
    from .notation import MODES, parse_key
    tpc, m = parse_key(f'{tonic} {mode}')
    home = _name(12 * (octave + 1) + tpc)
    last = tail[0].split()[:-1] + [f'{home}:{tail[0].split()[-1].split(":")[1]}']
    melody = a + b[:-1] + [' '.join(last)] if bars >= 2 else a
    return ' | '.join(melody[:bars])


def song(style='abyss', key=None, tempo=None, bars=4, seed=1, lyrics=None, name=None):
    """Complete song in a style (sections intro/verse/chorus/verse/chorus/outro), with a sung lead.
    style: abyss | takopi | jumping | angelic. lyrics replace the default syllables (kana, Russian, English)."""
    from .notation import parse_key
    if style not in SONG_STYLES:
        raise ValueError(f'стиль: {", ".join(SONG_STYLES)}')
    s = SONG_STYLES[style]
    rnd = random.Random(seed)
    tpc, mode = parse_key(key or s['key'])
    tonic = NAMES[tpc]
    full_key = f'{tonic} {mode}'
    lyr = lyrics or s['lyrics']
    slow = [[2, 1, 1], [1, 1, 2], [1.5, 0.5, 2], [3, 1], [1, 1, 1, 1]]
    mid = [[1, 1, 1, 1], [1.5, 0.5, 1, 1], [0.5, 0.5, 1, 2], [1, 0.5, 0.5, 2], [2, 1, 1]]
    jumpy = [[0.5, 0.5, 0.5, 0.5, 1, 1], [0.5, 0.25, 0.25, 0.5, 0.5, 2], [1, 0.5, 0.5, 0.5, 0.5, 1], [0.75, 0.75, 0.5, 2]]
    verse_chords, chorus_chords = s['verse'], s['chorus']
    sections = {'intro': {'bars': 2}, 'verse': {'bars': bars}, 'chorus': {'bars': bars}, 'outro': {'bars': 2}}
    arrange = 'intro verse chorus verse chorus outro'
    tracks = []
    if style == 'abyss':
        tracks = [
            {'name': 'челеста', 'instrument': 'celesta', 'style': 'arp', 'arp_step': 0.5, 'chord_octave': 5, 'gain': 0.45,
             'parts': {'intro': {'chords': verse_chords}, 'verse': {'chords': verse_chords}, 'chorus': {'chords': chorus_chords},
                       'outro': {'chords': 'i'}}, 'effects': [{'type': 'reverb', 'size': 1.0, 'mix': 0.4}]},
            {'name': 'арфа', 'instrument': 'harp', 'style': 'arp_updown', 'arp_step': 0.25, 'chord_octave': 3, 'gain': 0.5,
             'parts': {'verse': {'chords': verse_chords}, 'chorus': {'chords': chorus_chords}},
             'effects': [{'type': 'reverb', 'size': 0.9, 'mix': 0.3}]},
            {'name': 'струнные', 'instrument': 'strings', 'chord_octave': 3, 'gain': 0.4,
             'parts': {'chorus': {'chords': chorus_chords}, 'outro': {'chords': 'i'}},
             'effects': [{'type': 'reverb', 'size': 1.0, 'mix': 0.35}]},
            {'name': 'контрабас', 'instrument': 'contrabass', 'style': 'root', 'pulse': 4, 'chord_octave': 2, 'gain': 0.45,
             'parts': {'verse': {'chords': verse_chords}, 'chorus': {'chords': chorus_chords}}},
            {'name': 'детский голос', 'preset': 'abyss chant', 'lyrics': lyr, 'gain': 0.8,
             'parts': {'verse': _tune(tonic, mode, bars, rnd, 5, slow), 'chorus': _tune(tonic, mode, bars, rnd, 5, slow)}},
            {'name': 'ангельский хор', 'preset': 'angel choir', 'chord_octave': 4, 'gain': 0.5,
             'parts': {'chorus': {'chords': chorus_chords}, 'outro': {'chords': 'i'}}},
        ]
    elif style == 'takopi':
        tracks = [
            {'name': 'гитара', 'instrument': 'gm:nylon guitar', 'style': 'strum', 'chord_octave': 3, 'gain': 0.55,
             'parts': {'intro': {'chords': verse_chords}, 'verse': {'chords': verse_chords}, 'chorus': {'chords': chorus_chords},
                       'outro': {'chords': 'I'}}},
            {'name': 'рояль', 'instrument': 'piano', 'style': 'arp', 'arp_step': 0.5, 'chord_octave': 4, 'gain': 0.45,
             'parts': {'verse': {'chords': verse_chords}, 'chorus': {'chords': chorus_chords}, 'outro': {'chords': 'I'}}},
            {'name': 'глокеншпиль', 'instrument': 'glockenspiel', 'gain': 0.3,
             'parts': {'chorus': _tune(tonic, mode, bars, random.Random(seed + 7), 5, slow)}},
            {'name': 'барабаны', 'kit': 'gm', 'gain': 0.45,
             'parts': {'verse': {'drums': {'kick': 'x.......x.......', 'rim': '....x.......x...', 'hat': 'o.o.o.o.o.o.o.o.'}},
                       'chorus': {'drums': {'kick': 'x.....x.x.......', 'snare': '....x.......x...', 'hat': 'x.x.x.x.x.x.x.x.'}}}},
            {'name': 'бас', 'instrument': 'bass guitar', 'style': 'root', 'pulse': 2, 'chord_octave': 2, 'gain': 0.55,
             'parts': {'verse': {'chords': verse_chords}, 'chorus': {'chords': chorus_chords}}},
            {'name': 'струнные', 'instrument': 'strings', 'chord_octave': 4, 'gain': 0.3,
             'parts': {'chorus': {'chords': chorus_chords}}},
            {'name': 'вокал', 'preset': 'anime vocal', 'lyrics': lyr, 'gain': 0.85,
             'parts': {'verse': _tune(tonic, mode, bars, rnd, 4, mid), 'chorus': _tune(tonic, mode, bars, rnd, 5, mid)}},
        ]
    elif style == 'jumping':
        tracks = [
            {'name': 'ударные', 'kit': 'synth', 'gain': 0.8,
             'parts': {'intro': {'drums': {'hat': 'x.x.x.x.x.x.x.x.'}},
                       'verse': {'drums': {'kick': 'x...x...x...x...', 'clap': '....x.......x...', 'hat': '..x...x...x...x.'}},
                       'chorus': {'drums': {'kick': 'x...x...x...x...', 'clap': '....x.......x...', 'ohat': '..x...x...x...x.', 'shaker': 'xxxxxxxxxxxxxxxx'}}}},
            {'name': 'плаки', 'instrument': 'synth:pluck', 'style': 'arp', 'arp_step': 0.25, 'chord_octave': 4, 'gain': 0.45,
             'parts': {'intro': {'chords': verse_chords}, 'verse': {'chords': verse_chords}, 'chorus': {'chords': chorus_chords}},
             'effects': [{'type': 'delay', 'time': '3/16', 'feedback': 0.3, 'mix': 0.2}]},
            {'name': 'пэд', 'instrument': 'synth:pad', 'chord_octave': 4, 'gain': 0.3,
             'parts': {'chorus': {'chords': chorus_chords}}, 'effects': [{'type': 'sidechain', 'every': 1, 'depth': 0.6}]},
            {'name': 'бас', 'instrument': 'gm:synth bass', 'style': 'root_octave', 'pulse': 0.5, 'chord_octave': 2, 'gain': 0.6,
             'parts': {'verse': {'chords': verse_chords}, 'chorus': {'chords': chorus_chords}}},
            {'name': 'голоса', 'preset': 'jumping voices', 'lyrics': lyr, 'gain': 0.8,
             'parts': {'verse': _tune(tonic, mode, bars, rnd, 5, jumpy, 0.35), 'chorus': _tune(tonic, mode, bars, rnd, 5, jumpy, 0.45)}},
        ]
    else:  # angelic
        tracks = [
            {'name': 'ангельский хор', 'preset': 'angel choir', 'chord_octave': 4, 'gain': 0.7,
             'parts': {'intro': {'chords': 'I'}, 'verse': {'chords': verse_chords}, 'chorus': {'chords': chorus_chords, 'chord_length': 2},
                       'outro': {'chords': 'I'}}},
            {'name': 'детский хор', 'instrument': 'детский хор', 'lyrics': lyr, 'gain': 0.6,
             'parts': {'chorus': _tune(tonic, mode, bars, rnd, 5, slow)},
             'effects': [{'type': 'shimmer', 'size': 1.0, 'mix': 0.4}]},
            {'name': 'орган', 'instrument': 'church organ', 'chord_octave': 3, 'gain': 0.3,
             'parts': {'verse': {'chords': verse_chords}, 'chorus': {'chords': chorus_chords, 'chord_length': 2}}},
            {'name': 'арфа', 'instrument': 'harp', 'style': 'arp_updown', 'arp_step': 0.5, 'chord_octave': 4, 'gain': 0.45,
             'parts': {'verse': {'chords': verse_chords}, 'chorus': {'chords': chorus_chords, 'chord_length': 2}}},
            {'name': 'струнные', 'instrument': 'strings', 'chord_octave': 3, 'gain': 0.35,
             'parts': {'chorus': {'chords': chorus_chords, 'chord_length': 2}, 'outro': {'chords': 'I'}}},
        ]
    return {'name': name or f'{style}_song', 'kind': 'music', 'tags': ['song', style], 'tempo': tempo or s['tempo'],
            'key': full_key, 'seed': seed, 'description': s['desc'], 'sections': sections, 'arrange': arrange,
            'tracks': tracks, 'master': {'normalize': -1, 'fade_out': 3,
                                         'effects': [{'type': 'compress', 'threshold': -16, 'ratio': 2.5}]}}
