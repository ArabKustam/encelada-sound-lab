"""MCP server for Encelada Sound Lab (stdio). An agent (Claude Code / Claude Desktop / Codex) composes music, makes
beats, remixes, designs SFX for Minecraft and edits sounds through these tools; every render lands in the shared
library and in the live feed of the web app (http://127.0.0.1:4790), so the person can watch, listen and edit.

Connect (Claude Code):  claude mcp add soundlab -s user -- <python> <path>/soundlab/mcp_server.py
"""
import json
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = 'soundlab'

from mcp.server.fastmcp import FastMCP, Image  # noqa: E402

from soundlab import analysis, composer, elevenlabs, engine, library, midi, notation, samples, sfz, voice  # noqa: E402

GUIDE = Path(__file__).resolve().parent / 'GUIDE.md'

mcp = FastMCP('Encelada Sound Lab', instructions="""Music, beats, remixes and SFX (Minecraft-ready). A sound = JSON recipe:
{"name", "tempo", "key"?, "tracks": [...], "master": {"effects", "normalize"}} + optional song form
"sections": {"verse": {"bars": 4}}, "arrange": "intro verse chorus verse chorus".
Track kinds:
- notes: "instrument": LIVE RECORDED (Sonatina orchestra, SFZ): "piano"|"рояль"|"violin"|"скрипка"|"violin pizzicato"|"cello"|
  "strings"|"flute"|"oboe"|"clarinet"|"trumpet"|"horn"|"tuba"|"harp"|"choir"|"хор"|"church organ"|"sso:<any .sfz name>";
  General MIDI (MuseScore General): "gm:guitar"|"distortion guitar"|"bass guitar"|"sax"|"gm:violin"…; synths "synth:musicbox";
  "noteblock:harp"; any sample {"sample": ref, "root": "C4"|"auto"}; layers {"layers": ["violin", "choir"]};
  SINGING (neural SoulX-Singer, sings the notes exactly): "голос"|"певица"|"мужской голос"|"хор голосов"|"хор певиц"|
  {"singer": "en_female"|"zh_female"|"zh_male", "takes": 4} + "lyrics": "la la la" | English words | kana "きみたちが" |
  Cyrillic «ля» (one syllable per note, "-" = hold on next note). Robotic Windows TTS voice only as "tts voice".
  NEURAL: ai_song (ACE-Step: full song with real vocals from caption+lyrics, Japanese too), ai_cover (re-perform MY
  arrangement as a produced song), ai_repaint, ai_sfx / sfx "ai" (Woosh: any SFX from an English description);
  TRACK PRESETS "preset": "angel choir"|"abyss chant"|"anime vocal"|"jumping voices" (instrument+effects, add notes/chords);
  content (one or more):
  "notes": "C4:1 E G:1/2 [C4 E G]:2 r:1 (A4 B)x2 > C!@0.9 -"  (:len in beats or w h q e s t, '.' dotted; r rest;
   - tie; [..] chord; (..)xN repeat; > < octave; ! accent ? soft @vel)
  "chords": "Am F C G/B" or "i VI III V7" (with key), "style": block|pulse|strum|arp|arp_down|arp_updown|alberti|root|root_fifth|root_octave
  "drums": {"kick": "x...x...", "snare": "....x...", "hat": "x.x.x.x."} + "kit": synth|808|gm|mc (step 0.25 beat; x X o g r t 1-9)
  per-section content: "parts": {"verse": "...", "chorus": {"drums": {...}}}; or "sections": "verse chorus" + "loop": true
- sfx: "sfx": scream|screech|growl|whisper|heartbeat|drone|wind|riser|impact|glitch|static|breathing|creak|chime|bubbles|ufo|souls|rumble|sting|
  scrape (claws on walls: material stone|wood|metal|nails|glass)|crawl|siren|giggle|voice_scream|mimic (text: "помогите"), "params", "at"
- audio: "source": "mc:entity.zombie.ambient"|"samples:x.wav"|"library:<id>"|"tts:Фраза голосом"|"tts:en:Phrase"|path; rate, semitones, fit_beats, reverse, slices+sequence ("0 1 0 1 2r 3:2 ."), loop, at
Every track: gain, pan, effects [...], automation {gain|pan|lowpass|detune: [[beat, value]...]}, mute, solo.
Workflow: guide() for full syntax → create_sound → read the analysis notes + look at spectrogram → edit_sound (patch
tracks by name) or preview(from_beat, to_beat) for quick checks → export_to_minecraft (mono for positional sounds,
variants for random variation). search_samples finds vanilla Minecraft sounds (4000+) and user samples.""")


def _compact_analysis(a):
    keep = ('seconds', 'peak_db', 'rms_db', 'crest_db', 'clipped_percent', 'bands_percent', 'brightness_hz',
            'stereo_width', 'onsets_per_s', 'tempo_bpm_estimate', 'key_estimate', 'pitch', 'silence_start_s',
            'silence_end_s', 'loudness_timeline_db', 'timeline_step_s', 'notes')
    return {k: a[k] for k in keep if k in a}


def _result(meta, images=True):
    folder = library.LIB / meta['id']
    info = {k: meta[k] for k in ('id', 'name', 'seconds', 'tempo', 'beats', 'tags') if k in meta}
    if meta.get('sections'):
        info['sections'] = [f'{s["name"]}@{s["at"]:g}' for s in meta['sections']]
    if meta.get('analysis'):
        info['analysis'] = _compact_analysis(meta['analysis'])
    out = [json.dumps(info, ensure_ascii=False)]
    if images:
        out += [Image(path=str(folder / 'spectrogram.png')), Image(path=str(folder / 'waveform.png'))]
    return out


@mcp.tool()
def guide(topic: str = '') -> str:
    """Documentation (GUIDE.md). No topic → table of contents; topic = words from a heading (e.g. 'нотация',
    'аккорды', 'ударные', 'сэмплы', 'ремикс', 'minecraft', 'эффекты', 'примеры', 'mcp')."""
    text = GUIDE.read_text(encoding='utf-8')
    sections, cur = [], None
    for line in text.splitlines():
        if line.startswith('## '):
            cur = [line]
            sections.append(cur)
        elif cur is not None:
            cur.append(line)
    if not topic:
        heads = [s[0][3:] for s in sections]
        return 'Разделы GUIDE.md (guide(topic="…")):\n' + '\n'.join(f'- {h}' for h in heads)
    words = topic.lower().split()
    hits = [s for s in sections if all(w in '\n'.join(s).lower() for w in words)]
    hits.sort(key=lambda s: -sum(w in s[0].lower() for w in words))
    if not hits:
        return f'нет раздела про {topic!r}; разделы: ' + ', '.join(s[0][3:] for s in sections)
    return '\n\n'.join('\n'.join(s) for s in hits[:2])


@mcp.tool()
def catalog(section: str = 'all') -> str:
    """What recipes can use. section: all | instruments | synths | gm | gm_aliases | drums | noteblock | sfx | effects |
    notation | samples."""
    return json.dumps(engine.catalog(section), ensure_ascii=False)


@mcp.tool()
def list_sounds(query: str = '') -> str:
    """Sounds in the library (newest first), optionally filtered by words in id/name/tags."""
    words = query.lower().split()
    out = []
    for s in library.list_sounds():
        text = ' '.join([s['id'], s.get('name', ''), ' '.join(s.get('tags', [])), s.get('description', '')]).lower()
        if all(w in text for w in words):
            out.append({k: s.get(k) for k in ('id', 'name', 'seconds', 'kind', 'tags', 'description')})
    return json.dumps(out, ensure_ascii=False)


@mcp.tool()
def get_sound(sound_id: str) -> str:
    """Recipe, metadata and the last analysis of one sound."""
    data = library.get(sound_id)
    a = library.LIB / sound_id / 'analysis.json'
    if a.exists():
        data['analysis'] = _compact_analysis(json.loads(a.read_text(encoding='utf-8')))
    data['meta'].pop('history', None)
    return json.dumps(data, ensure_ascii=False)


@mcp.tool()
def create_sound(recipe: dict, note: str = ''):
    """Render a new sound from a recipe (compact notation allowed) and save it. Returns id, analysis (notes =
    plain-language problems), spectrogram and waveform (section lines marked)."""
    return _result(library.create(recipe, 'claude', note))


@mcp.tool()
def update_sound(sound_id: str, recipe: dict, note: str = ''):
    """Replace the whole recipe of an existing sound (old version kept in history) and re-render."""
    return _result(library.save_render(sound_id, recipe, 'claude', note))


@mcp.tool()
def edit_sound(sound_id: str, tracks: dict | None = None, set: dict | None = None, remove_tracks: list | None = None,
               note: str = ''):
    """Patch a sound without resending the recipe, then re-render.
    tracks: {"<track name>": {fields to replace}} — unknown name adds a new track; a field set to null is removed.
    set: top-level fields (tempo, key, master, sections, arrange…; null removes). remove_tracks: [names]."""
    recipe = library.edit(sound_id, set, tracks, remove_tracks)
    return _result(library.save_render(sound_id, recipe, 'claude', note or 'правка'))


@mcp.tool()
def preview(recipe: dict | None = None, sound_id: str = '', from_beat: float = 0, to_beat: float = 0):
    """Quick render of a part (beats from_beat..to_beat; 0/0 = whole) of a recipe or of a saved sound, without
    saving to history. Goes to library id `_preview` (visible in the web app)."""
    if recipe is None:
        if not sound_id:
            raise ValueError('нужен recipe или sound_id')
        recipe = library.get(sound_id)['recipe']
    span = (from_beat, to_beat) if to_beat > from_beat else None
    return _result(library.preview(recipe, span, 'claude'))


@mcp.tool()
def analyze_sound(sound_id: str):
    """Full analysis of a library sound (loudness over time, bands, onsets, tempo/key/pitch estimates, warnings)."""
    folder = library.LIB / sound_id
    a = analysis.analyze_file(folder / 'audio.wav') if (folder / 'audio.wav').exists() else \
        analysis.analyze_file(folder / 'audio.ogg')
    return [json.dumps(a, ensure_ascii=False), Image(path=str(folder / 'spectrogram.png'))]


@mcp.tool()
def search_samples(query: str = '', source: str = 'all', limit: int = 30) -> str:
    """Find samples to use or modify: vanilla Minecraft sounds (events like entity.zombie.ambient and files like
    mob/zombie/say1, note/harp), user files in soundlab/samples, library sounds. source: all | mc | samples | library.
    Use the returned `ref` as audio "source", as {"sample": ref} instrument, or as a drum-grid row name."""
    res = samples.search(query, source, limit)
    return json.dumps({'results': res, 'stats': samples.stats()}, ensure_ascii=False)


@mcp.tool()
def sample_info(ref: str):
    """Analyze a sample reference (duration, pitch/root note, loudness, bands) + its spectrogram — to pick a root
    note for the sampler or to judge what to cut/process."""
    x = samples.load(ref)
    a = analysis.analyze(x, 44100)
    folder = library.LIB / '_sample'
    folder.mkdir(parents=True, exist_ok=True)
    library.spectrogram_png(x, 44100, folder / 'spectrogram.png')
    a['ref'] = ref
    a['path'] = str(samples.resolve(ref))
    return [json.dumps(a, ensure_ascii=False), Image(path=str(folder / 'spectrogram.png'))]


@mcp.tool()
def search_instruments(query: str = '') -> str:
    """Find instruments: live recorded SFZ (presets like violin/choir and every .sfz articulation: 'violin pizzicato',
    'cello legato', 'horns staccato'…), General MIDI programs, singing voices. Use the returned `use` string as instrument."""
    words = query.lower().split()
    out = []
    for name, path in sfz.installed_presets().items():
        if all(w in name for w in words):
            out.append({'use': name, 'kind': 'живая запись (пресет)', 'sfz': path})
    for key in sorted(sfz.all_sfz()):
        if all(w in key for w in words):
            out.append({'use': key, 'kind': 'живая запись (sfz)'})
    for i, n in enumerate(engine.GM_NAMES):
        if all(w in n.lower() for w in words):
            out.append({'use': f'gm:{i}', 'kind': 'General MIDI', 'name': n})
    for k, v in notation.VOICE_WORDS.items():
        if all(w in k for w in words):
            out.append({'use': k, 'kind': 'пение (нужен lyrics)', 'params': v})
    return json.dumps(out[:80], ensure_ascii=False)


@mcp.tool()
def speak(text: str, voice_name: str = 'auto', effects: list | None = None, name: str = '', semitones: float = 0,
          rate: float = 0):
    """Spoken phrase with a real voice (Windows TTS: irina — Russian, zira — English, auto by text) saved to the library
    as editable audio: pitch it down for a monster, add reverb for a spirit, chop it, layer it into SFX or music."""
    ref = 'tts:' + ('' if voice_name == 'auto' else voice_name + ':') + text
    tr = {'name': 'фраза', 'type': 'audio', 'source': ref, 'gain': 1.0, 'effects': effects or []}
    if semitones:
        tr['semitones'] = semitones
    if rate:
        tr['rate'] = rate
    recipe = {'name': name or 'phrase', 'kind': 'sfx', 'tags': ['voice', 'phrase'], 'tempo': 60, 'tracks': [tr],
              'description': f'фраза: {text}', 'master': {'normalize': -1}}
    return _result(library.create(recipe, 'claude', 'фраза голосом'))


@mcp.tool()
def neural_status() -> str:
    """Which neural engines are installed/running (ACE-Step songs, SoulX-Singer vocals, Woosh SFX)."""
    from soundlab import neural
    return json.dumps(neural.status(), ensure_ascii=False)


@mcp.tool()
def ai_song(caption: str, lyrics: str = '', duration: float = 60, bpm: int = 0, key: str = '', language: str = 'en',
            instrumental: bool = False, seed: int = -1, name: str = 'ai_song', steps: int = 8):
    """ACE-Step 1.5: a finished song with REAL vocals from a style caption + lyrics (like Suno, local, MIT).
    caption: genre/mood/instruments/voice in English ("gentle anime ending, j-pop ballad, soft female vocal, piano,
    strings"). lyrics: with section tags [verse] [chorus] [bridge] [outro]; language: ja|en|ru|zh|ko… (50+).
    duration 10–600 s. The first call loads the models (slow); later ~10–40 s per song on an RTX 4090."""
    from soundlab import neural
    path = neural.acestep(caption, lyrics, duration, bpm or None, key or None, language, instrumental, seed,
                          steps=steps, log=lambda m: library.event('ai', m))
    mp = path.with_suffix('.json')
    meta = json.loads(mp.read_text(encoding='utf-8')) if mp.exists() else {}
    return _result(library.from_file(path, name, 'music', ['ai', 'acestep'], f'ACE-Step: {caption}', 'нейро-песня ACE-Step',
                                     extra={'ai': {'engine': 'acestep', 'caption': caption, 'lyrics': lyrics,
                                                   'language': language, 'seed': meta.get('seed_value')}}))


@mcp.tool()
def ai_cover(source: str, caption: str, lyrics: str = '', strength: float = 0.6, language: str = 'en',
             duration: float = 0, seed: int = -1, name: str = 'ai_cover'):
    """ACE-Step cover: re-perform an existing audio (library sound id or file path) in a new style / with vocals,
    keeping its structure and melody. strength 1.0 = stick to the source closely, ~0.3 = loose restyle. Use it to turn
    MY composed arrangement (notes + instruments) into a real-sounding produced song with singing."""
    import soundfile as sf
    from soundlab import neural
    src = library.LIB / source / 'audio.wav' if (library.LIB / source).is_dir() else Path(source)
    dur = duration or sf.info(str(src)).duration
    path = neural.acestep(caption, lyrics, dur, language=language, seed=seed, task_type='cover', src_audio=src,
                          cover_strength=strength, log=lambda m: library.event('ai', m))
    return _result(library.from_file(path, name, 'music', ['ai', 'acestep', 'cover'], f'ACE-Step cover: {caption}',
                                     'нейро-кавер ACE-Step'))


@mcp.tool()
def ai_repaint(sound_id: str, start: float, end: float, caption: str, lyrics: str = '', language: str = 'en',
               seed: int = -1, name: str = ''):
    """ACE-Step repaint: regenerate only seconds start..end of a sound (fix a line, change a chorus), keep the rest."""
    import soundfile as sf
    from soundlab import neural
    src = library.LIB / sound_id / 'audio.wav'
    path = neural.acestep(caption, lyrics, sf.info(str(src)).duration, language=language, seed=seed,
                          task_type='repaint', src_audio=src, repaint=(start, end), log=lambda m: library.event('ai', m))
    return _result(library.from_file(path, name or f'{sound_id}_repaint', 'music', ['ai', 'acestep', 'repaint'],
                                     f'repaint {start}-{end} s: {caption}', 'нейро-правка фрагмента'))


@mcp.tool()
def ai_sfx(prompt: str, duration: float = 5, seed: int = 0, variants: int = 1, quality: bool = False,
           effects: list | None = None, name: str = ''):
    """Woosh (Sony AI): any sound effect from an English description — "long claws scraping a stone wall",
    "small creatures giggling in the dark", "monstrous distorted scream". Saved as an editable recipe (sfx "ai"),
    so it can be layered with other tracks and effects. variants>1 → several seeds one after another (pick the best).
    Weights are CC-BY-NC: fine for a hobby server, not for selling."""
    tracks = []
    for v in range(max(1, variants)):
        tracks.append({'name': f'ai {v + 1}', 'type': 'sfx', 'sfx': 'ai', 'at': v * (duration + 1),
                       'params': {'prompt': prompt, 'duration': duration, 'seed': seed + v,
                                  'model': 'quality' if quality else 'fast'}, 'effects': effects or [], 'gain': 1.0})
    recipe = {'name': name or 'ai_sfx', 'kind': 'sfx', 'tags': ['sfx', 'ai', 'woosh'], 'tempo': 60,
              'description': f'Woosh: {prompt}', 'tracks': tracks, 'master': {'normalize': -1, 'trim': True}}
    return _result(library.create(recipe, 'claude', f'нейро-SFX: {prompt[:50]}'))


@mcp.tool()
def compose_song(style: str = 'abyss', key: str = '', tempo: int = 0, bars: int = 4, seed: int = 1, lyrics: str = '',
                 name: str = '', render: bool = True):
    """Full sung song (intro/verse/chorus/verse/chorus/outro): abyss (ethereal, child voice in an invented language +
    angel choir, «Made in Abyss» mood) | takopi (gentle anime ending, Japanese vocal, guitar/piano) | jumping (bouncy
    vocal chops, «Jumping Voices» mood) | angelic (hymn: angel choir, organ, harp). lyrics: kana, Russian or English
    syllables. render=False → recipe to rewrite the melody/lyrics yourself first (recommended for a real song)."""
    recipe = composer.song(style, key or None, tempo or None, bars, seed, lyrics or None, name or None)
    if not render:
        return json.dumps(recipe, ensure_ascii=False)
    return _result(library.create(recipe, 'claude', f'песня {style}'))


@mcp.tool()
def compose_beat(style: str = 'lofi', tempo: int = 0, key: str = '', bars: int = 4, seed: int = 1, lead: bool = True,
                 name: str = '', render: bool = True):
    """Starter beat: lofi | trap | house | rock | chiptune | noteblock (Minecraft note blocks). Drums grid + chords +
    bass + generated lead, sections intro/main/drop. render=False returns the recipe to edit first."""
    recipe = composer.beat(style, tempo or None, key or None, bars, seed, name or None, lead)
    if not render:
        return json.dumps(recipe, ensure_ascii=False)
    return _result(library.create(recipe, 'claude', f'бит {style}'))


@mcp.tool()
def compose_calm(key: str = 'F', scale: str = 'lydian', tempo: int = 72, bars: int = 8, seed: int = 1,
                 lead: str = 'musicbox', name: str = 'calm', render: bool = True):
    """Gentle C418-like piece (pad, broken piano chords, music-box motif). render=False returns the recipe only."""
    recipe = composer.calm(key, scale, tempo, bars, seed, lead, name)
    return _result(library.create(recipe, 'claude', 'сочинено compose_calm')) if render else json.dumps(recipe, ensure_ascii=False)


@mcp.tool()
def compose_horror(key: str = 'C', tempo: int = 72, bars: int = 8, intensity: float = 0.7, seed: int = 2,
                   name: str = 'dread', render: bool = True):
    """Dark ambience: drone, detuned strings, low piano clusters, heartbeat, whispers, screech."""
    recipe = composer.horror(key, tempo, bars, intensity, seed, name)
    return _result(library.create(recipe, 'claude', 'сочинено compose_horror')) if render else json.dumps(recipe, ensure_ascii=False)


@mcp.tool()
def morph(at_beat: float = 24, style: str = 'melt', transition: float = 4, calm: dict | None = None,
          horror: dict | None = None, name: str = 'calm_to_horror'):
    """A good hallucination that turns into horror on beat `at_beat`. style: melt | cut | fade."""
    recipe = composer.morph(composer.calm(**(calm or {})), composer.horror(**(horror or {})), at_beat, style, transition, name)
    return _result(library.create(recipe, 'claude', f'переход {style} на доле {at_beat}'))


@mcp.tool()
def make_sfx(kind: str, params: dict | None = None, effects: list | None = None, name: str = '', repeat: dict | None = None):
    """One synthesized SFX generator (see catalog('sfx')) with optional effects chain. For layered SFX (several
    generators + Minecraft samples) use create_sound with several tracks."""
    track = {'name': kind, 'type': 'sfx', 'sfx': kind, 'params': params or {}, 'effects': effects or [], 'gain': 1.0}
    if repeat:
        track['repeat'] = repeat
    recipe = {'name': name or kind, 'kind': 'sfx', 'tags': ['sfx', kind], 'tempo': 60, 'tracks': [track], 'master': {'normalize': -1}}
    return _result(library.create(recipe, 'claude', f'SFX {kind}'))


@mcp.tool()
def transform_audio(source: str, effects: list | None = None, name: str = 'transformed', rate: float = 0,
                    semitones: float = 0, reverse: bool = False, trim: list | None = None, tempo: float = 0,
                    fit_beats: float = 0, slices: int = 0, sequence: str = '', step: float = 0):
    """Process / remix existing audio. source: library id, sample ref (mc:…, samples:…) or file path.
    rate = tape speed (pitch+length), semitones = pitch keeping length, trim = [start_s, end_s], fit_beats = stretch
    to N beats at `tempo`, slices + sequence = chop & rearrange ("0 1 0 1 2r 3:2 ." ; step = beats per slot)."""
    src = f'library:{source}' if (library.LIB / source).is_dir() else source
    tr = {'name': 'исходник', 'type': 'audio', 'source': src, 'gain': 1.0, 'effects': effects or []}
    for k, v in (('rate', rate), ('semitones', semitones), ('reverse', reverse), ('trim', trim), ('fit_beats', fit_beats),
                 ('slices', slices), ('sequence', sequence), ('step', step)):
        if v:
            tr[k] = v
    recipe = {'name': name, 'kind': 'audio', 'tags': ['обработка'], 'tempo': tempo or 120, 'tracks': [tr],
              'master': {'normalize': -1}}
    return _result(library.create(recipe, 'claude', 'обработка звука'))


@mcp.tool()
def import_midi(path: str, name: str = '', render: bool = True):
    """MIDI file → recipe (GM instruments per track). Then change instruments/tempo/effects with edit_sound to remix."""
    recipe = midi.midi_to_recipe(path, name or None)
    if not render:
        return json.dumps(recipe, ensure_ascii=False)[:60000]
    return _result(library.create(recipe, 'claude', f'импорт MIDI {Path(path).name}'))


@mcp.tool()
def export_midi(sound_id: str, path: str) -> str:
    """Write the notes tracks of a sound to a .mid file (for a DAW or note-block converters)."""
    return json.dumps(midi.recipe_to_midi(library.get(sound_id)['recipe'], path), ensure_ascii=False)


@mcp.tool()
def export_to_minecraft(sound_id: str, key: str, pack_dir: str = '', mono: bool = True, stream: bool = False,
                        subtitle: str = '', variants: int = 1, volume: float = 1.0, pitch: float = 1.0,
                        attenuation: int = 0, pitch_spread: float = 0.0) -> str:
    """Put the sound into a resource pack (assets/<ns>/sounds/soundlab/*.ogg + sounds.json + pack.mcmeta if missing).
    key «ns:event.name». mono=True for positional sounds (required for distance attenuation); stream=True for long
    music. variants>1 renders extra versions (other seed, ±pitch_spread semitones) that Minecraft picks at random.
    Returns /playsound command and a Bukkit/Paper Java line."""
    return json.dumps(library.export_minecraft(sound_id, key, pack_dir or None, mono, stream, subtitle or None, variants,
                                               volume, pitch, attenuation or None, pitch_spread), ensure_ascii=False)


@mcp.tool()
def export_file(sound_id: str, path: str, format: str = '', mono: bool = False) -> str:
    """Save the rendered audio anywhere as .ogg or .wav (e.g. into a plugin's resources)."""
    return json.dumps(library.export_file(sound_id, path, format or None, mono), ensure_ascii=False)


@mcp.tool()
def elevenlabs_sfx(prompt: str, duration: float = 0, name: str = '', loop: bool = False, prompt_influence: float = 0.4):
    """Optional (needs ELEVENLABS_API_KEY): text → sound effect via ElevenLabs, saved to the library as editable
    audio (then transform_audio / layer it in create_sound). English prompts work best."""
    data = elevenlabs.sound_effect(prompt, duration or None, prompt_influence, loop)
    return _result(elevenlabs.to_library(data, name or prompt[:30], prompt, 'sfx'))


@mcp.tool()
def elevenlabs_music(prompt: str, seconds: int = 30, name: str = ''):
    """Optional (needs ELEVENLABS_API_KEY): text → music via ElevenLabs, saved to the library as audio."""
    data = elevenlabs.music(prompt, seconds)
    return _result(elevenlabs.to_library(data, name or prompt[:30], prompt, 'music'))


@mcp.tool()
def revert_sound(sound_id: str, version: int):
    """Go back to an older recipe version (history/<n>.json) and re-render."""
    return _result(library.revert(sound_id, version, 'claude'))


@mcp.tool()
def delete_sound(sound_id: str) -> str:
    """Move a sound to the library trash (recoverable)."""
    library.delete(sound_id)
    return 'ok'


if __name__ == '__main__':
    mcp.run()
