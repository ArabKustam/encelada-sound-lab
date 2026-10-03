"""Encelada Sound Lab — local web app: library of sounds, recipe editor, live «what is being created» feed.

Run:  python -m soundlab.server        (from the studio folder)  →  http://127.0.0.1:4790
Everything stays on this computer; no network access is needed.
"""
import io
import json
import mimetypes
import os
import sys
import threading
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = 'soundlab'

from soundlab import analysis, composer, engine, library, notation, samples  # noqa: E402

WEB = Path(__file__).resolve().parent / 'web'
PORT = int(os.environ.get('SOUNDLAB_PORT', 4790))
ALLOWED_FILES = {'audio.ogg', 'audio.wav', 'audio_mono.ogg', 'waveform.png', 'spectrogram.png', 'analysis.json'}


def background(fn, *args):
    def run():
        try:
            fn(*args)
        except Exception as exc:  # noqa: BLE001 — ошибка уже записана в ленту событий
            traceback.print_exc()
    threading.Thread(target=run, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, data, status=200, ctype='application/json'):
        body = json.dumps(data, ensure_ascii=False).encode() if ctype == 'application/json' else data
        self.send_response(status)
        self.send_header('Content-Type', ctype + ('; charset=utf-8' if ctype.startswith(('application/json', 'text')) else ''))
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(n) if n else b''
        return raw

    def json_body(self):
        raw = self.body()
        return json.loads(raw or b'{}')

    def guard(self):
        # только локальные запросы (как у студии)
        host = self.headers.get('Host', '')
        return host.startswith(('127.0.0.1', 'localhost'))

    def do_GET(self):
        if not self.guard():
            return self.send({'error': 'только localhost'}, 403)
        url = urlparse(self.path)
        path = url.path
        try:
            if path in ('/', '/index.html'):
                return self.send((WEB / 'index.html').read_bytes(), ctype='text/html')
            if path.startswith('/web/'):
                f = (WEB / path[5:]).resolve()
                if WEB not in f.parents or not f.exists():
                    return self.send({'error': 'нет файла'}, 404)
                return self.send(f.read_bytes(), ctype=mimetypes.guess_type(f.name)[0] or 'application/octet-stream')
            if path == '/api/catalog':
                return self.send(engine.catalog())
            if path == '/api/sounds':
                return self.send(library.list_sounds())
            if path.startswith('/api/sound/'):
                sid = path.split('/')[3]
                data = library.get(sid)
                hist = sorted((library.LIB / sid / 'history').glob('*.json')) if (library.LIB / sid / 'history').exists() else []
                data['versions'] = [int(h.stem) for h in hist]
                return self.send(data)
            if path.startswith('/api/file/'):
                _, _, _, sid, name = path.split('/')
                if name not in ALLOWED_FILES or '..' in sid:
                    return self.send({'error': 'нельзя'}, 403)
                f = library.LIB / sid / name
                if not f.exists():
                    return self.send({'error': 'нет файла'}, 404)
                return self.send(f.read_bytes(), ctype=mimetypes.guess_type(name)[0] or 'application/octet-stream')
            if path == '/api/samples':
                q = parse_qs(url.query)
                return self.send({'results': samples.search(q.get('q', [''])[0], q.get('source', ['all'])[0], 80),
                                  'stats': samples.stats()})
            if path == '/api/sample':
                ref = parse_qs(url.query).get('ref', [''])[0]
                if not ref.startswith(('mc:', 'samples:', 'library:')):
                    return self.send({'error': 'только mc:, samples:, library:'}, 403)
                f = samples.resolve(ref)
                ctype = mimetypes.guess_type(f.name)[0] or ('audio/ogg' if ref.startswith('mc:') else 'application/octet-stream')
                return self.send(f.read_bytes(), ctype=ctype)
            if path == '/api/events':
                offset = int(parse_qs(url.query).get('offset', ['0'])[0])
                events, new = library.events_since(offset)
                return self.send({'events': events, 'offset': new})
            return self.send({'error': 'нет такого адреса'}, 404)
        except KeyError as exc:
            return self.send({'error': str(exc)}, 404)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return self.send({'error': str(exc)}, 500)

    def do_POST(self):
        if not self.guard():
            return self.send({'error': 'только localhost'}, 403)
        path = urlparse(self.path).path
        try:
            if path == '/api/render':
                body = self.json_body()
                recipe = body['recipe']
                author = body.get('author', 'user')
                sid = body.get('id') or None
                if not sid:
                    sid = library.slug(recipe.get('name', 'sound'))
                    if (library.LIB / sid).exists():
                        sid = f'{sid}_{uuid.uuid4().hex[:4]}'
                background(library.save_render, sid, recipe, author, body.get('note', ''))
                return self.send({'id': sid, 'started': True})
            if path == '/api/expand':
                body = self.json_body()
                return self.send({'recipe': notation.expand_recipe(body['recipe'])})
            if path == '/api/expand_track':
                body = self.json_body()
                r = body['recipe']
                i = int(body['index'])
                return self.send({'tracks': notation.expand_track(r['tracks'][i], r, i)})
            if path == '/api/ai_song':
                body = self.json_body()

                def job():
                    from soundlab import neural
                    library.event('ai', 'ACE-Step: генерирую песню…', 'start', 'user')
                    try:
                        p = neural.acestep(body['caption'], body.get('lyrics', ''), float(body.get('duration', 60)),
                                           language=body.get('language', 'en'), instrumental=bool(body.get('instrumental')),
                                           log=lambda m: library.event('ai', m))
                    except Exception as exc:
                        library.event('ai', f'ошибка: {exc}', 'error')
                        raise
                    library.from_file(p, body.get('name') or 'ai_song', 'music', ['ai', 'acestep'],
                                      f'ACE-Step: {body["caption"]}', 'нейро-песня', author='user')
                background(job)
                return self.send({'started': True})
            if path == '/api/ai_sfx':
                body = self.json_body()
                recipe = {'name': body.get('name') or 'ai_sfx', 'kind': 'sfx', 'tags': ['sfx', 'ai'], 'tempo': 60,
                          'description': f'Woosh: {body["prompt"]}',
                          'tracks': [{'type': 'sfx', 'sfx': 'ai', 'at': v * (float(body.get('duration', 5)) + 1),
                                      'params': {'prompt': body['prompt'], 'duration': float(body.get('duration', 5)),
                                                 'seed': v}} for v in range(int(body.get('variants', 3)))],
                          'master': {'normalize': -1}}
                sid = library.slug(recipe['name']) + '_' + uuid.uuid4().hex[:4]
                background(library.save_render, sid, recipe, 'user', 'нейро-SFX')
                return self.send({'id': sid})
            if path == '/api/preview':
                body = self.json_body()
                span = (float(body['from']), float(body['to'])) if body.get('to') else None
                background(library.preview, body['recipe'], span, 'user')
                return self.send({'id': library.PREVIEW, 'started': True})
            if path == '/api/compose':
                body = self.json_body()
                kind = body.get('kind', 'calm')
                params = body.get('params', {})
                if kind == 'beat':
                    recipe = composer.beat(**params)
                elif kind == 'song':
                    recipe = composer.song(**params)
                elif kind == 'calm':
                    recipe = composer.calm(**params)
                elif kind == 'horror':
                    recipe = composer.horror(**params)
                elif kind == 'morph':
                    calm_p = params.pop('calm', {})
                    hor_p = params.pop('horror', {})
                    recipe = composer.morph(composer.calm(**calm_p), composer.horror(**hor_p), **params)
                else:
                    return self.send({'error': 'kind: beat | calm | horror | morph'}, 400)
                return self.send({'recipe': recipe})
            if path == '/api/audition':
                body = self.json_body()
                import soundfile as sf
                inst = body.get('instrument', 'piano')
                recipe = {'tempo': 60, 'tracks': [{'type': 'notes', 'instrument': inst,
                                                   'notes': [[0, body.get('length', 0.6), body.get('note', 'C4'), body.get('velocity', 0.8)]],
                                                   'effects': body.get('effects', [])}],
                          'master': {'normalize': -3}}
                if body.get('sfx'):
                    recipe['tracks'] = [{'type': 'sfx', 'sfx': body['sfx'], 'params': body.get('params', {}),
                                         'effects': body.get('effects', [])}]
                audio, sr, _ = engine.render(recipe)
                buf = io.BytesIO()
                sf.write(buf, audio, sr, format='WAV', subtype='PCM_16')
                return self.send(buf.getvalue(), ctype='audio/wav')
            if path == '/api/delete':
                library.delete(self.json_body()['id'])
                return self.send({'ok': True})
            if path == '/api/revert':
                body = self.json_body()
                background(library.revert, body['id'], body['version'], 'user')
                return self.send({'ok': True})
            if path == '/api/export':
                body = self.json_body()
                return self.send(library.export_minecraft(body['id'], body['key'], body.get('pack_dir') or None,
                                                          body.get('mono', True), body.get('stream', False),
                                                          body.get('subtitle')))
            if path == '/api/upload':
                q = parse_qs(urlparse(self.path).query)
                name = library.slug(q.get('name', ['upload'])[0])
                ext = Path(q.get('name', ['x.wav'])[0]).suffix.lower() or '.wav'
                if ext not in ('.wav', '.ogg', '.flac', '.mp3'):
                    return self.send({'error': 'нужен wav/ogg/flac/mp3'}, 400)
                sid = f'{name}_{uuid.uuid4().hex[:4]}'
                folder = library.LIB / sid
                folder.mkdir(parents=True)
                src = folder / f'source{ext}'
                src.write_bytes(self.body())
                recipe = {'name': name, 'kind': 'audio', 'tags': ['загружено'],
                          'tracks': [{'name': 'исходник', 'type': 'audio', 'source': str(src), 'gain': 1.0, 'effects': []}],
                          'master': {'normalize': -1}}
                background(library.save_render, sid, recipe, 'user', 'загружен файл')
                return self.send({'id': sid})
            return self.send({'error': 'нет такого адреса'}, 404)
        except (engine.RecipeError, notation.NotationError, samples.SampleError, ValueError) as exc:
            return self.send({'error': str(exc)}, 400)
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            return self.send({'error': str(exc)}, 500)


def main():
    library.LIB.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    print(f'Encelada Sound Lab: http://127.0.0.1:{PORT}')
    server.serve_forever()


if __name__ == '__main__':
    main()
