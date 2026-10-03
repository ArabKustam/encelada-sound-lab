"""Standard MIDI files without dependencies: import (.mid → recipe, for remixes/covers) and export (recipe → .mid,
to open in a DAW or a Minecraft note-block tool)."""
import struct
from pathlib import Path

from . import engine, notation

SYNTH_TO_GM = {'piano': 0, 'epiano': 4, 'bell': 14, 'musicbox': 10, 'pad': 89, 'strings': 48, 'choir': 52, 'pluck': 24,
               'bass': 33, 'organ': 16, 'saw': 81, 'square': 80, 'triangle': 80, 'sine': 80}
NOTEBLOCK_TO_GM = {'harp': 46, 'bass': 32, 'guitar': 24, 'flute': 73, 'bell': 9, 'icechime': 8, 'xylobone': 13,
                   'iron_xylophone': 11, 'cow_bell': 113, 'didgeridoo': 109, 'bit': 80, 'banjo': 105, 'pling': 4}


class MidiError(ValueError):
    pass


# ----------------------------------------------------------------------------------------------------- reading

def _vlq(data, i):
    value = 0
    while True:
        b = data[i]
        i += 1
        value = (value << 7) | (b & 0x7F)
        if not b & 0x80:
            return value, i


def read_midi(path):
    """→ {'ppq', 'tempo_bpm', 'tracks': [{'name', 'events': [(tick, kind, channel, a, b)]}]}"""
    data = Path(path).read_bytes()
    if data[:4] != b'MThd':
        raise MidiError('это не MIDI-файл (нет MThd)')
    hlen, fmt, ntrk, division = struct.unpack('>IHHH', data[4:14])
    if division & 0x8000:
        raise MidiError('SMPTE-время в MIDI не поддерживается')
    i = 8 + hlen
    tracks, tempo = [], None
    for _ in range(ntrk):
        while data[i:i + 4] != b'MTrk':
            if i >= len(data):
                break
            i += 8 + struct.unpack('>I', data[i + 4:i + 8])[0]
        length = struct.unpack('>I', data[i + 4:i + 8])[0]
        j, end = i + 8, i + 8 + length
        tick, status, name, events = 0, 0, '', []
        while j < end:
            delta, j = _vlq(data, j)
            tick += delta
            b = data[j]
            if b == 0xFF:
                mtype = data[j + 1]
                mlen, j = _vlq(data, j + 2)
                payload = data[j:j + mlen]
                j += mlen
                if mtype == 0x51 and tempo is None:
                    tempo = 60_000_000 / int.from_bytes(payload, 'big')
                elif mtype == 0x03 and not name:
                    name = payload.decode('latin-1', 'replace')
                continue
            if b in (0xF0, 0xF7):
                slen, j = _vlq(data, j + 1)
                j += slen
                continue
            if b & 0x80:
                status = b
                j += 1
            kind, ch = status & 0xF0, status & 0x0F
            if kind in (0xC0, 0xD0):
                a, bb = data[j], 0
                j += 1
            else:
                a, bb = data[j], data[j + 1]
                j += 2
            events.append((tick, kind, ch, a, bb))
        tracks.append({'name': name, 'events': events})
        i = end
    return {'ppq': division, 'tempo_bpm': round(tempo or 120.0, 2), 'tracks': tracks, 'format': fmt}


def midi_to_recipe(path, name=None, max_tracks=24):
    """MIDI file → Sound Lab recipe (one track per MIDI track+channel; GM programs → real instruments)."""
    m = read_midi(path)
    ppq = m['ppq']
    out = []
    for tr in m['tracks']:
        program = {}
        open_notes = {}
        by_ch = {}
        for tick, kind, ch, a, b in tr['events']:
            if kind == 0xC0:
                program.setdefault(ch, a)
            elif kind == 0x90 and b > 0:
                open_notes.setdefault((ch, a), []).append((tick, b))
            elif kind == 0x80 or (kind == 0x90 and b == 0):
                stack = open_notes.get((ch, a))
                if stack:
                    start, vel = stack.pop(0)
                    by_ch.setdefault(ch, []).append([round(start / ppq, 4), round(max(tick - start, 1) / ppq, 4), a,
                                                     round(vel / 127, 3)])
        for ch, notes in sorted(by_ch.items()):
            notes.sort(key=lambda n: (n[0], n[2]))
            if ch == 9:
                inst = {'gm_drums': True}
                label = 'ударные'
            else:
                p = program.get(ch, 0)
                inst = {'gm': p}
                label = engine.GM_NAMES[p]
            out.append({'name': (tr['name'] or label)[:40], 'type': 'notes', 'instrument': inst, 'notes': notes, 'gain': 0.7})
    if not out:
        raise MidiError('в MIDI нет нот')
    out = sorted(out, key=lambda t: -len(t['notes']))[:max_tracks]
    return {'name': name or Path(path).stem, 'kind': 'music', 'tags': ['midi'], 'tempo': m['tempo_bpm'],
            'description': f'импорт из {Path(path).name}', 'tracks': out,
            'master': {'normalize': -1, 'effects': [{'type': 'reverb', 'size': 0.5, 'mix': 0.15}]}}


# ----------------------------------------------------------------------------------------------------- writing

def _wvlq(v):
    out = [v & 0x7F]
    v >>= 7
    while v:
        out.append((v & 0x7F) | 0x80)
        v >>= 7
    return bytes(reversed(out))


def _program_for(inst):
    if 'voice' in inst:
        return 52 if int(inst.get('voices', 1)) > 1 else 53
    if 'sfz' in inst:
        stem = Path(inst['sfz']).stem.lower()
        for word, prog in (('piano', 0), ('harpsichord', 6), ('celeste', 8), ('marimba', 12), ('organ', 19),
                           ('violas', 41), ('viola', 41), ('violins', 48), ('violin', 40), ('celli', 42), ('cello', 42),
                           ('basses', 43), ('strings', 48), ('harp', 46), ('timpani', 47), ('chorus', 52),
                           ('piccolo', 72), ('flute', 73), ('oboe', 68), ('anglais', 69), ('clarinet', 71),
                           ('bassoon', 70), ('trumpet', 56), ('trombone', 57), ('tuba', 58), ('horn', 60), ('brass', 61)):
            if word in stem:
                return prog
        return 0
    if 'gm' in inst:
        return int(inst['gm'])
    if 'synth' in inst:
        return SYNTH_TO_GM.get(inst['synth'], 0)
    if 'sample' in inst:
        nb = str(inst['sample']).rsplit('/', 1)[-1].replace('note_block.', '')
        return NOTEBLOCK_TO_GM.get(nb, 0)
    return 0


def recipe_to_midi(recipe, path, ppq=480):
    """Write notes tracks of a (compact or explicit) recipe to a type-1 MIDI file. SFX/audio tracks are skipped."""
    from .notation import GM_DRUM_KEYS
    r = notation.expand_recipe(recipe)
    tempo = float(r.get('tempo', 120))
    chunks = [b'\x00\xFF\x51\x03' + int(60_000_000 / tempo).to_bytes(3, 'big') + b'\x00\xFF\x2F\x00']
    channel = 0
    skipped = []
    for tr in r['tracks']:
        if tr.get('type', 'notes') != 'notes' or not tr.get('notes'):
            skipped.append(tr.get('name', '?'))
            continue
        inst = tr.get('instrument', {})
        drums = 'kit' in inst or inst.get('gm_drums') or 'drum' in inst
        ch = 9 if drums else [c for c in range(16) if c != 9][channel % 15]
        if not drums:
            channel += 1
        evs = []
        for n in tr['notes']:
            if drums:
                key = n[2] if isinstance(n[2], (int, float)) else GM_DRUM_KEYS.get(engine.DRUM_ALIASES.get(n[2], n[2]),
                                                                                   GM_DRUM_KEYS.get(str(n[2]), 38))
            else:
                key = engine.note_to_midi(n[2])
            key = int(round(key))
            if not 0 <= key <= 127:
                continue
            vel = int(max(1, min(127, (n[3] if len(n) > 3 else 0.8) * 127)))
            s = int(round(n[0] * ppq))
            e = max(s + 1, int(round((n[0] + n[1]) * ppq)))
            evs.append((s, 1, bytes([0x90 | ch, key, vel])))
            evs.append((e, 0, bytes([0x80 | ch, key, 0])))
        evs.sort(key=lambda e: (e[0], e[1]))
        name = str(tr.get('name', '')).encode('utf-8')[:120]
        body = b'\x00\xFF\x03' + _wvlq(len(name)) + name
        if not drums:
            body += b'\x00' + bytes([0xC0 | ch, _program_for(inst) & 0x7F])
        now = 0
        for t, _, msg in evs:
            body += _wvlq(t - now) + msg
            now = t
        body += b'\x00\xFF\x2F\x00'
        chunks.append(body)
    data = b'MThd' + struct.pack('>IHHH', 6, 1, len(chunks), ppq)
    for c in chunks:
        data += b'MTrk' + struct.pack('>I', len(c)) + c
    Path(path).write_bytes(data)
    return {'file': str(path), 'tracks': len(chunks) - 1, 'skipped_non_note_tracks': skipped}
