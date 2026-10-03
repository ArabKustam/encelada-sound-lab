"""SFZ sampler: plays real recorded instruments (Sonatina Symphonic Orchestra and any other .sfz library).

Supported: <control>/<global>/<master>/<group>/<region>, #include, #define, default_path, sample, key/lokey/hikey,
pitch_keycenter, lovel/hivel, transpose, tune, volume, pan, amp_veltrack, offset, loop_mode/loop_start/loop_end,
ampeg_attack/ampeg_release, trigger (attack only), seq_length/seq_position (round robin), lorand/hirand.

Libraries live in soundlab/instruments/<name>/ ; instruments are addressed as "sso:violin solo 1 sustain" (words of
the .sfz file name) or by preset aliases (REAL_PRESETS) like "violin", "скрипка", "хор", "grand piano".
"""
import math
import re
from functools import lru_cache
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
INSTRUMENTS = HERE / 'instruments'
NOTE_RE = re.compile(r'^([a-gA-G])([#b]?)(-?\d+)$')
PC = {'c': 0, 'd': 2, 'e': 4, 'f': 5, 'g': 7, 'a': 9, 'b': 11}

# alias → (library, words that must be in the .sfz name, words that must not). First found wins.
REAL_PRESETS = {
    'grand piano': [('salamander', 'salamander grand piano v3', ''), ('sso', 'grand piano', '')],
    'sso piano': [('sso', 'grand piano', '')],
    'violin': [('sso', 'violin solo 1 sustain (looped)', ''), ('sso', 'violin solo 1 sustain', '')],
    'violin legato': [('sso', 'violin solo 1 legato', '')],
    'violin staccato': [('sso', 'violin solo 1 staccato', '')],
    'violin pizzicato': [('sso', 'violin solo 1 pizzicato', '')],
    'violin tremolo': [('sso', 'violin solo 2 tremolo', '')],
    'violins': [('sso', '1st violins sustain', 'ks')],
    'viola': [('sso', 'viola solo sustain', 'ks')],
    'violas': [('sso', 'violas sustain', 'ks')],
    'cello': [('sso', 'cello solo sustain', 'ks')],
    'cellos': [('sso', 'celli sustain', 'ks')],
    'contrabass': [('sso', 'basses sustain', 'ks')],
    'strings': [('sso', 'all strings sustain', 'ks'), ('sso', '1st violins sustain', 'ks')],
    'strings pizzicato': [('sso', 'all strings pizzicato', 'ks'), ('sso', '1st violins pizzicato', 'ks')],
    'strings staccato': [('sso', 'all strings staccato', 'ks'), ('sso', '1st violins staccato', 'ks')],
    'flute': [('sso', 'flute solo 1 sustain (looped)', ''), ('sso', 'flute solo 1 sustain', '')],
    'flute staccato': [('sso', 'flute solo 1 staccato', '')],
    'flutes': [('sso', 'flutes sustain', 'ks')],
    'piccolo': [('sso', 'piccolo solo sustain', 'ks')],
    'alto flute': [('sso', 'alto flute solo sustain', 'ks')],
    'oboe': [('sso', 'oboe solo sustain', 'ks')],
    'english horn': [('sso', 'cor anglais solo sustain', 'ks')],
    'clarinet': [('sso', 'clarinet solo sustain', 'ks')],
    'bass clarinet': [('sso', 'bass clarinet solo sustain', 'ks')],
    'bassoon': [('sso', 'bassoon solo sustain', 'ks')],
    'trumpet': [('sso', 'trumpet solo sustain', 'ks')],
    'trumpets': [('sso', 'trumpets sustain', 'ks')],
    'horn': [('sso', 'horn solo sustain', 'ks')],
    'horns': [('sso', 'horns sustain', 'ks')],
    'trombone': [('sso', 'tenor trombone solo sustain', 'ks')],
    'trombones': [('sso', 'trombones sustain', 'ks')],
    'tuba': [('sso', 'tuba sustain (looped)', ''), ('sso', 'tuba sustain', '')],
    'brass': [('sso', 'all brass sustain', 'ks')],
    'choir': [('sso', 'mixed chorus', '')],
    'large choir': [('sso', 'large chorus', '')],
    'harp': [('sso', 'concert harp', '')],
    'harpsichord': [('sso', 'harpsichord full', ''), ('sso', 'harpsichord 8', '')],
    'celesta': [('sso', 'celeste', '')],
    'marimba': [('sso', 'marimba', '')],
    'vibraphone': [('sso', 'vibraphone', '')],
    'church organ': [('sso', 'great - open diapason 8ft', '')],
    'organ flute': [('sso', 'great - flute 4ft', '')],
    'organ bass': [('sso', 'pedal - bourdon 16ft', '')],
    'timpani': [('sso', 'timpani', '')],
    'glockenspiel': [('sso', 'glockenspiel', '')],
    'xylophone': [('sso', 'xylophone', '')],
}
REAL_ALIASES = {
    'piano': 'grand piano', 'пианино': 'grand piano', 'фортепиано': 'grand piano', 'рояль': 'grand piano',
    'скрипка': 'violin', 'скрипки': 'violins', 'альт': 'viola', 'виолончель': 'cello', 'контрабас': 'contrabass',
    'double bass': 'contrabass', 'струнные': 'strings', 'оркестр': 'strings', 'string ensemble': 'strings',
    'pizzicato': 'strings pizzicato', 'пиццикато': 'strings pizzicato', 'флейта': 'flute', 'пикколо': 'piccolo',
    'гобой': 'oboe', 'кларнет': 'clarinet', 'фагот': 'bassoon', 'труба': 'trumpet', 'валторна': 'horn',
    'french horn': 'horn', 'тромбон': 'trombone', 'туба': 'tuba', 'духовые': 'brass', 'хор': 'choir',
    'большой хор': 'large choir', 'арфа': 'harp', 'клавесин': 'harpsichord', 'челеста': 'celesta',
    'маримба': 'marimba', 'вибрафон': 'vibraphone', 'церковный орган': 'church organ', 'литавры': 'timpani',
    'глокеншпиль': 'glockenspiel', 'ксилофон': 'xylophone',
}


class SfzError(ValueError):
    pass


def note_num(v):
    v = str(v).strip()
    if re.fullmatch(r'-?\d+', v):
        return int(v)
    m = NOTE_RE.match(v)
    if not m:
        raise SfzError(f'sfz: не понимаю ноту {v!r}')
    return PC[m.group(1).lower()] + (1 if m.group(2) == '#' else -1 if m.group(2) == 'b' else 0) + 12 * (int(m.group(3)) + 1)


# ----------------------------------------------------------------------------------------------------- parsing

ROOT_OF = []


def _read_text(path, defines, depth=0):
    text = Path(path).read_text(encoding='utf-8', errors='replace')
    text = re.sub(r'/\*.*?\*/', ' ', text, flags=re.S)
    text = re.sub(r'//[^\n]*', ' ', text)
    out = []
    for line in text.splitlines():
        m = re.match(r'\s*#define\s+(\$\w+)\s+(.+?)\s*$', line)
        if m:
            defines[m.group(1)] = m.group(2)
            continue
        for k, v in sorted(defines.items(), key=lambda kv: -len(kv[0])):
            line = line.replace(k, v)
        if '#include' in line and depth < 8:          # includes can sit anywhere in a line
            parts = re.split(r'#include\s+"([^"]+)"', line)
            for k, part in enumerate(parts):
                if k % 2 == 0:
                    out.append(part)
                else:
                    inc = Path(path).parent / part
                    if not inc.exists():
                        inc = Path(ROOT_OF[0]) / part if ROOT_OF else inc
                    if inc.exists():
                        out.append(_read_text(inc, defines, depth + 1))
            continue
        out.append(line)
    return '\n'.join(out)


OPCODE_RE = re.compile(r'(\w+)=')


def _opcodes(chunk):
    """'sample=a b.wav lokey=c4' → dict; values may contain spaces (sample paths)."""
    res = {}
    matches = list(OPCODE_RE.finditer(chunk))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(chunk)
        res[m.group(1)] = chunk[m.end():end].strip()
    return res


@lru_cache(maxsize=64)
def load_sfz(path):
    """→ list of region dicts with absolute 'path' and inherited opcodes."""
    path = Path(path)
    ROOT_OF[:] = [str(path.parent)]
    text = _read_text(path, {})
    control, glob, master, group = {}, {}, {}, {}
    regions = []
    for m in re.finditer(r'<(\w+)>([^<]*)', text):
        head, body = m.group(1), _opcodes(m.group(2))
        if head == 'control':
            control.update(body)
        elif head == 'global':
            glob, master, group = body, {}, {}
        elif head == 'master':
            master, group = body, {}
        elif head == 'group':
            group = body
        elif head == 'region':
            r = {**glob, **master, **group, **body}
            if 'sample' not in r:
                continue
            base = path.parent / control.get('default_path', '')
            r['path'] = str((base / r['sample'].replace('\\', '/')).resolve())
            regions.append(r)
    cc = {}
    for k, v in control.items():
        mm = re.match(r'set_(hd)?cc(\d+)$', k)
        if mm:
            try:
                cc[int(mm.group(2))] = float(v) * (127 if mm.group(1) else 1)
            except ValueError:
                pass

    def cc_ok(r):                                     # regions needing a pedal/controller we don't press are skipped
        for k, v in r.items():
            mm = re.match(r'(lo|hi)cc(\d+)$', k)
            if mm:
                val = cc.get(int(mm.group(2)), 0)
                try:
                    lim = float(v)
                except ValueError:
                    continue
                if (mm.group(1) == 'lo' and val < lim) or (mm.group(1) == 'hi' and val > lim):
                    return False
        return True
    regions = [r for r in regions if cc_ok(r)]
    sw_default = next((r['sw_default'] for r in regions if 'sw_default' in r), None)
    if sw_default:                                    # keyswitch libraries: keep the default articulation
        try:
            d = note_num(sw_default)
            regions = [r for r in regions if 'sw_last' not in r or note_num(r['sw_last']) == d]
        except SfzError:
            pass
    if not regions:
        raise SfzError(f'в {path.name} нет регионов с сэмплами')
    for r in regions:
        if 'key' in r:
            r['_lo'] = r['_hi'] = r['_center'] = note_num(r['key'])
        r['_lo'] = note_num(r.get('lokey', r.get('_lo', 0)))
        r['_hi'] = note_num(r.get('hikey', r.get('_hi', 127)))
        r['_center'] = note_num(r.get('pitch_keycenter', r.get('_center', r.get('key', 60)))) if r.get('pitch_keycenter', '') != 'sample' else 60
        r['_lovel'] = int(float(r.get('lovel', 0)))
        r['_hivel'] = int(float(r.get('hivel', 127)))
        r['_db'] = float(r.get('volume', 0)) + float(r.get('group_volume', 0)) + float(r.get('master_volume', 0))             + float(r.get('global_volume', 0)) + 20 * math.log10(max(float(r.get('amplitude', 100)), 1e-3) / 100)
    return regions


# ----------------------------------------------------------------------------------------------------- lookup

@lru_cache(maxsize=1)
def all_sfz():
    """{'sso:violin solo 1 sustain': Path, ...} for every .sfz under instruments/ (and samples/)."""
    out = {}
    for root in (INSTRUMENTS, HERE / 'samples'):
        if not root.exists():
            continue
        for p in root.rglob('*.sfz'):
            if 'includes' in p.parts:
                continue
            lib = p.relative_to(root).parts[0] if root == INSTRUMENTS else 'samples'
            out[f'{lib}:{p.stem.lower()}'] = p
    return out


def find(query):
    """'sso:violin solo 1 sustain' / 'violin solo sustain' / a path → Path of the best .sfz."""
    q = str(query).strip()
    if q.lower().endswith('.sfz'):
        p = Path(q) if Path(q).is_absolute() else INSTRUMENTS / q
        if p.exists():
            return p
    lib, _, words = q.lower().partition(':') if ':' in q else ('', '', q.lower())
    items = all_sfz()
    if f'{lib}:{words}' in items:
        return items[f'{lib}:{words}']
    ws = words.replace('(', ' ').replace(')', ' ').split()
    cands = [(k, p) for k, p in items.items() if (not lib or k.startswith(lib + ':')) and all(w in k for w in ws)]
    if not cands:
        raise SfzError(f'нет SFZ-инструмента {query!r} (установлено: {len(items)}); список — catalog("real")')
    cands.sort(key=lambda kp: (' ks' in kp[0], len(kp[0])))
    return cands[0][1]


def preset(name):
    """Alias ('violin', 'скрипка', 'хор') → Path of an installed .sfz, or None if the library isn't installed."""
    key = REAL_ALIASES.get(name.lower().strip(), name.lower().strip())
    for lib, must, mustnot in REAL_PRESETS.get(key, []):
        items = all_sfz()
        exact = f'{lib}:{must}'
        if exact in items:
            return items[exact]
        ws = must.replace('(', ' ').replace(')', ' ').split()
        cands = [(k, p) for k, p in items.items() if k.startswith(lib + ':') and all(w in k for w in ws)
                 and not (mustnot and mustnot in k.split())]
        if cands:
            cands.sort(key=lambda kp: len(kp[0]))
            return cands[0][1]
    return None


def installed_presets():
    return {name: str(preset(name).relative_to(INSTRUMENTS)) for name in REAL_PRESETS if preset(name)}


# ----------------------------------------------------------------------------------------------------- playback

@lru_cache(maxsize=512)
def _sample(path):
    import soundfile as sf
    data, sr = sf.read(path, dtype='float32', always_2d=True)
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    return data[:, :2], sr


class Player:
    """Renders notes of one .sfz instrument."""

    def __init__(self, path, sr=44100, params=None):
        self.path = Path(path)
        self.regions = [r for r in load_sfz(str(self.path)) if r.get('trigger', 'attack') in ('attack', 'first', 'legato')]
        self.sr = sr
        self.p = params or {}
        self.rr = {}
        self.rng = np.random.default_rng(int(self.p.get('seed', 0)))
        self.norm = self._norm()

    def _norm(self):
        """Level match: a mezzo-forte middle note peaks around -9 dBFS whatever the library's recording level."""
        keys = sorted({(r['_lo'] + r['_hi']) // 2 for r in self.regions})
        key = min(keys, key=lambda k: abs(k - 64))
        r = self.pick(key, 96)
        self.rr.clear()
        data, _ = _sample(r['path'])
        peak = float(np.abs(data).max()) * 10 ** (r['_db'] / 20)
        return 0.35 / max(peak, 1e-4)

    def pick(self, key, vel127):
        c = [r for r in self.regions if r['_lo'] <= key <= r['_hi'] and r['_lovel'] <= vel127 <= r['_hivel']]
        if not c:                                                        # out of range → nearest region
            c = sorted(self.regions, key=lambda r: min(abs(key - r['_lo']), abs(key - r['_hi'])))[:1]
        seq = [r for r in c if 'seq_position' in r]
        if seq:
            n = self.rr.get(key, 0)
            self.rr[key] = n + 1
            length = int(float(seq[0].get('seq_length', len(seq))))
            pos = n % max(length, 1) + 1
            c = [r for r in seq if int(float(r['seq_position'])) == pos] or seq
        rnd = [r for r in c if 'lorand' in r or 'hirand' in r]
        if rnd:
            x = self.rng.uniform()
            c = [r for r in rnd if float(r.get('lorand', 0)) <= x < float(r.get('hirand', 1))] or rnd
        return c[0]

    def note(self, midi, hold, vel):
        """midi (float), hold seconds, vel 0..1 → stereo float32 with release tail."""
        key = int(round(midi))
        r = self.pick(key, int(max(1, min(127, vel * 127))))
        data, fsr = _sample(r['path'])
        semis = midi - r['_center'] + float(r.get('transpose', 0)) + float(r.get('tune', 0)) / 100
        ratio = 2 ** (semis / 12) * fsr / self.sr
        release = float(self.p.get('release', r.get('ampeg_release', 0.25)))
        release = max(release, 0.03)
        need = int((hold + release) * self.sr)                          # output samples wanted
        src = data[int(float(r.get('offset', 0))):]
        mode = r.get('loop_mode', 'loop_continuous' if 'loop_start' in r else 'no_loop')
        one_shot = mode == 'one_shot' or self.p.get('one_shot')
        if mode in ('loop_continuous', 'loop_sustain') and 'loop_start' in r and 'loop_end' in r:
            ls, le = int(float(r['loop_start'])), int(float(r['loop_end']))
            if 0 <= ls < le <= len(data) and need * ratio > len(src):
                loop = data[ls:le + 1]
                reps = int(math.ceil((need * ratio - len(data)) / max(len(loop), 1))) + 1
                src = np.concatenate([data[:le + 1]] + [loop] * reps)
        n_out = min(need, int(len(src) / ratio) - 1) if not one_shot else int(len(src) / ratio) - 1
        if n_out <= 1:
            return np.zeros((2, 2), np.float32)
        idx = np.arange(n_out) * ratio
        i0 = idx.astype(np.int64)
        frac = (idx - i0)[:, None].astype(np.float32)
        y = src[i0] * (1 - frac) + src[np.minimum(i0 + 1, len(src) - 1)] * frac
        t = np.arange(n_out) / self.sr
        env = np.ones(n_out, np.float32)
        att = float(self.p.get('attack', r.get('ampeg_attack', 0.0)))
        if att > 0:
            env *= np.clip(t / att, 0, 1)
        if not one_shot:
            env *= np.where(t > hold, np.exp(-(t - hold) / release * 4.6), 1.0).astype(np.float32)
        veltrack = float(r.get('amp_veltrack', 100)) / 100
        gain = 10 ** (r['_db'] / 20) * (1 - veltrack * (1 - vel ** 2)) * self.norm
        y = y * (env * gain)[:, None]
        pan = float(r.get('pan', 0)) / 100
        if pan:
            y[:, 0] *= min(1, 1 - pan)
            y[:, 1] *= min(1, 1 + pan)
        return y.astype(np.float32)


def render_track(track, sr, beat, log=None, detune=None):
    """Notes track with instrument {'sfz': path|name} → stereo array."""
    inst = track['instrument']
    path = inst['_sfz_path'] if '_sfz_path' in inst else find(inst['sfz'])
    params = {**inst.get('params', {}), **{k: v for k, v in inst.items() if k in ('release', 'attack', 'one_shot')}}
    player = Player(path, sr, params)
    if log:
        log(f'  живой инструмент {Path(path).stem} ({len(player.regions)} сэмплов), нот: {len(track.get("notes", []))}')
    pieces = []
    gain = float(inst.get('gain', 1.0))
    from .engine import note_to_midi
    for n in track.get('notes', []):
        start, length = float(n[0]), float(n[1])
        vel = float(n[3]) if len(n) > 3 else 0.8
        opts = n[4] if len(n) > 4 and isinstance(n[4], dict) else {}
        m = note_to_midi(n[2]) + float(opts.get('pitch', 0)) + (detune(start) if detune else 0.0)
        pieces.append((int(start * beat * sr), player.note(m, length * beat, vel) * gain * float(opts.get('gain', 1))))
    end = max((s + len(a) for s, a in pieces), default=2)
    out = np.zeros((end, 2), np.float32)
    for s, a in pieces:
        out[s:s + len(a)] += a
    return out
