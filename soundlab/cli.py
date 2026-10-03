"""Command line for Sound Lab (the same library the web app shows).

python -m soundlab.cli render recipe.json [--id ID]            # render (create or update)
python -m soundlab.cli preview recipe.json|ID [from to]        # quick render of beats from..to → library/_preview
python -m soundlab.cli beat lofi|trap|house|rock|chiptune|noteblock [tempo=.. key="A minor" bars=4 seed=1]
python -m soundlab.cli song abyss|takopi|jumping|angelic [key="D minor" lyrics="きみたちが"]
python -m soundlab.cli calm|horror [key=val ...]                 # compose + render
python -m soundlab.cli morph at_beat=24 style=melt
python -m soundlab.cli sfx scream duration=2.5
python -m soundlab.cli analyze ID|file.wav                       # numbers + plain-language notes
python -m soundlab.cli search zombie hurt [--mc|--samples|--library]
python -m soundlab.cli sample mc:note/harp                       # pitch / length of a sample
python -m soundlab.cli midi-import song.mid [name]
python -m soundlab.cli midi-export ID out.mid
python -m soundlab.cli export ID drugs:halluc.name [pack_dir] [--stereo] [--stream] [--variants=3]
python -m soundlab.cli export-file ID path.ogg|path.wav [--mono]
python -m soundlab.cli guide [topic]    |    catalog [section]    |    list
"""
import json
import sys
from pathlib import Path

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = 'soundlab'

from soundlab import analysis, composer, engine, library, midi, samples  # noqa: E402


def kv(args):
    out = {}
    for a in args:
        if '=' in a and not a.startswith('--'):
            k, v = a.split('=', 1)
            try:
                v = json.loads(v)
            except ValueError:
                pass
            out[k] = v
    return out


def flag(rest, name, default=None):
    for a in rest:
        if a.startswith(f'--{name}='):
            return a.split('=', 1)[1]
    return default


def show(meta):
    a = meta.pop('analysis', None)
    meta.pop('history', None)
    print(json.dumps(meta, ensure_ascii=False))
    if a:
        print('анализ:', '; '.join(a['notes']))


def main(argv):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if not argv:
        print(__doc__)
        return
    cmd, rest = argv[0], argv[1:]
    if cmd == 'render':
        recipe = json.loads(Path(rest[0]).read_text(encoding='utf-8'))
        sid = rest[rest.index('--id') + 1] if '--id' in rest else None
        show(library.save_render(sid, recipe, 'claude') if sid else library.create(recipe, 'claude'))
    elif cmd == 'preview':
        src = rest[0]
        recipe = json.loads(Path(src).read_text(encoding='utf-8')) if src.endswith('.json') else library.get(src)['recipe']
        span = (float(rest[1]), float(rest[2])) if len(rest) >= 3 else None
        show(library.preview(recipe, span, 'claude'))
        print('файл:', library.LIB / library.PREVIEW / 'audio.wav')
    elif cmd == 'beat':
        p = kv(rest[1:])
        recipe = composer.beat(rest[0] if rest else 'lofi', p.get('tempo'), p.get('key'), p.get('bars', 4),
                               p.get('seed', 1), p.get('name'), p.get('lead', True))
        show(library.create(recipe, 'claude', 'cli beat'))
    elif cmd == 'song':
        p = kv(rest[1:])
        recipe = composer.song(rest[0] if rest else 'abyss', p.get('key'), p.get('tempo'), p.get('bars', 4),
                               p.get('seed', 1), p.get('lyrics'), p.get('name'))
        show(library.create(recipe, 'claude', 'cli song'))
    elif cmd in ('calm', 'horror'):
        show(library.create(getattr(composer, cmd)(**kv(rest)), 'claude', 'cli ' + cmd))
    elif cmd == 'morph':
        p = kv(rest)
        recipe = composer.morph(composer.calm(**p.pop('calm', {})), composer.horror(**p.pop('horror', {})), **p)
        show(library.create(recipe, 'claude', 'cli morph'))
    elif cmd == 'sfx':
        kind = rest[0]
        recipe = {'name': kind, 'kind': 'sfx', 'tempo': 60, 'tags': ['sfx', kind],
                  'tracks': [{'type': 'sfx', 'sfx': kind, 'params': kv(rest[1:]), 'gain': 1.0}], 'master': {'normalize': -1}}
        show(library.create(recipe, 'claude', 'cli sfx'))
    elif cmd == 'analyze':
        target = rest[0]
        path = Path(target) if Path(target).exists() else library.LIB / target / 'audio.wav'
        print(json.dumps(analysis.analyze_file(path), ensure_ascii=False, indent=1))
    elif cmd == 'search':
        source = next((a[2:] for a in rest if a in ('--mc', '--samples', '--library')), 'all')
        for r in samples.search(' '.join(a for a in rest if not a.startswith('--')), source, 60):
            print(r['ref'], {k: v for k, v in r.items() if k != 'ref'})
    elif cmd == 'sample':
        a = analysis.analyze(samples.load(rest[0]), 44100)
        print(json.dumps({k: a.get(k) for k in ('seconds', 'pitch', 'peak_db', 'bands_percent', 'notes')}, ensure_ascii=False))
    elif cmd == 'midi-import':
        show(library.create(midi.midi_to_recipe(rest[0], rest[1] if len(rest) > 1 else None), 'claude', 'cli midi'))
    elif cmd == 'midi-export':
        print(json.dumps(midi.recipe_to_midi(library.get(rest[0])['recipe'], rest[1]), ensure_ascii=False))
    elif cmd == 'export':
        pack = rest[2] if len(rest) > 2 and not rest[2].startswith('--') else None
        print(json.dumps(library.export_minecraft(rest[0], rest[1], pack, '--stereo' not in rest, '--stream' in rest,
                                                  variants=int(flag(rest, 'variants', 1))), ensure_ascii=False))
    elif cmd == 'export-file':
        print(json.dumps(library.export_file(rest[0], rest[1], None, '--mono' in rest), ensure_ascii=False))
    elif cmd == 'guide':
        from soundlab.mcp_server import guide
        print(guide(' '.join(rest)))
    elif cmd == 'catalog':
        print(json.dumps(engine.catalog(rest[0] if rest else 'all'), ensure_ascii=False, indent=1))
    elif cmd == 'list':
        for s in library.list_sounds():
            print(f'{s["id"]:30} {s.get("seconds", "?"):>7} с  {", ".join(s.get("tags", []))}')
    else:
        print(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
