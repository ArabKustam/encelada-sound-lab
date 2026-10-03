"""Optional: ElevenLabs text-to-sound-effects and text-to-music. The generated audio lands in the library as an
ordinary `audio` recipe, so it can be chopped, pitched, layered with synth SFX and exported like anything else.

Key: env ELEVENLABS_API_KEY or soundlab/config.json {"elevenlabs_api_key": "..."} (config.json is in .gitignore).
Without a key the tools just say so — everything else in Sound Lab works offline.
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = 'https://api.elevenlabs.io/v1'


class ElevenLabsError(RuntimeError):
    pass


def api_key():
    key = os.environ.get('ELEVENLABS_API_KEY')
    if key:
        return key
    cfg = HERE / 'config.json'
    if cfg.exists():
        try:
            return json.loads(cfg.read_text(encoding='utf-8')).get('elevenlabs_api_key')
        except ValueError:
            pass
    return None


def _post(path, body, timeout=180):
    key = api_key()
    if not key:
        raise ElevenLabsError('нет ключа ElevenLabs: задайте ELEVENLABS_API_KEY или soundlab/config.json '
                              '{"elevenlabs_api_key": "..."}; без него работают все встроенные генераторы')
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(), method='POST',
                                 headers={'xi-api-key': key, 'Content-Type': 'application/json', 'Accept': 'audio/mpeg'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')[:400]
        raise ElevenLabsError(f'ElevenLabs {exc.code}: {detail}') from None
    except urllib.error.URLError as exc:
        raise ElevenLabsError(f'нет связи с ElevenLabs: {exc.reason}') from None


def sound_effect(prompt, duration=None, prompt_influence=0.4, loop=False):
    """English prompt works best. duration 0.5–30 s or None (auto). Returns mp3 bytes."""
    body = {'text': prompt, 'prompt_influence': float(prompt_influence)}
    if duration:
        body['duration_seconds'] = float(max(0.5, min(30.0, duration)))
    if loop:
        body['loop'] = True
    return _post('/sound-generation', body)


def music(prompt, seconds=30, extra=None):
    """Text-to-music. Returns mp3 bytes."""
    body = {'prompt': prompt, 'music_length_ms': int(max(10, min(300, seconds)) * 1000)}
    body.update(extra or {})
    return _post('/music', body, timeout=600)


def to_library(audio_bytes, name, prompt, kind, author='claude'):
    """Save generated mp3 as a library sound (source.mp3 + audio recipe) and render it."""
    from . import library
    import uuid
    sid = f'{library.slug(name)}_{uuid.uuid4().hex[:4]}'
    folder = library.LIB / sid
    folder.mkdir(parents=True)
    (folder / 'source.mp3').write_bytes(audio_bytes)
    recipe = {'name': name, 'kind': kind, 'tags': ['elevenlabs', kind], 'tempo': 60,
              'description': f'ElevenLabs: {prompt}',
              'tracks': [{'name': 'elevenlabs', 'type': 'audio', 'source': f'library:{sid}/source.mp3', 'gain': 1.0, 'effects': []}],
              'master': {'normalize': -1}}
    return library.save_render(sid, recipe, author, f'ElevenLabs {kind}: {prompt[:60]}')
