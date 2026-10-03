"""Download the free instrument libraries and neural engines (too big for git):

    python -m soundlab.install                 # instruments: sso + salamander + musescore
    python -m soundlab.install salamander      # Salamander Grand Piano (Yamaha C5, ~1 GB, CC-BY 3.0)
    python -m soundlab.install sso             # Sonatina Symphonic Orchestra (~1.4 GB, CC Sampling Plus 1.0)
    python -m soundlab.install musescore       # MuseScore General SoundFont (~216 MB, MIT)
    python -m soundlab.install neural          # all three neural engines below (needs git, uv, NVIDIA GPU)
    python -m soundlab.install acestep         # ACE-Step 1.5 — songs with vocals (MIT; models ~20 GB download on first use)
    python -m soundlab.install singer          # SoulX-Singer — sings notes (Apache 2.0; ~6 GB)
    python -m soundlab.install woosh           # Woosh (Sony AI) — text → SFX (CC-BY-NC, non-commercial; ~4.7 GB)
"""
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINES = HERE.parent / 'engines'
LIBS = {
    'salamander': {'url': 'https://codeload.github.com/sfzinstruments/SalamanderGrandPiano/zip/refs/heads/master',
                   'dest': HERE / 'instruments' / 'salamander', 'zip_root': 'SalamanderGrandPiano-master',
                   'about': 'Salamander Grand Piano — живой рояль Yamaha C5 (SFZ)'},
    'sso': {'url': 'https://codeload.github.com/peastman/sso/zip/refs/heads/master', 'dest': HERE / 'instruments' / 'sso',
            'zip_root': 'sso-master', 'about': 'Sonatina Symphonic Orchestra — живой оркестр, хор (SFZ)'},
    'musescore': {'url': 'https://ftp.osuosl.org/pub/musescore/soundfont/MuseScore_General/MuseScore_General.sf2',
                  'dest': HERE / 'soundfonts' / 'MuseScore_General.sf2', 'about': 'MuseScore General — 128 GM-инструментов'},
}
WOOSH_ZIPS = ['Woosh-DFlow', 'Woosh-Flow', 'Woosh-AE', 'TextConditionerA']


def _download(url, path):
    tmp = path.with_suffix(path.suffix + '.part')
    with urllib.request.urlopen(url, timeout=60) as r, open(tmp, 'wb') as f:
        total = int(r.headers.get('Content-Length') or 0)
        done = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f'\r  {done / 1e6:.0f} / {total / 1e6:.0f} МБ', end='', flush=True)
    print()
    tmp.replace(path)


def install_lib(name):
    lib = LIBS[name]
    if lib['dest'].exists():
        print(f'{name}: уже установлено ({lib["dest"]})')
        return
    print(f'{name}: {lib["about"]} — скачиваю…')
    lib['dest'].parent.mkdir(parents=True, exist_ok=True)
    if lib['url'].endswith('.sf2'):
        _download(lib['url'], lib['dest'])
    else:
        z = lib['dest'].parent / f'{name}.zip'
        _download(lib['url'], z)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(lib['dest'].parent)
        shutil.move(str(lib['dest'].parent / lib['zip_root']), str(lib['dest']))
        z.unlink()
    print(f'{name}: готово')


def sh(cmd, cwd=None):
    print('  $', ' '.join(map(str, cmd)))
    subprocess.run([str(c) for c in cmd], cwd=cwd, check=True)


def clone(repo, dest):
    if not dest.exists():
        ENGINES.mkdir(parents=True, exist_ok=True)
        sh(['git', 'clone', '--depth', '1', f'https://github.com/{repo}.git', dest])


def install_acestep():
    d = ENGINES / 'ACE-Step-1.5'
    clone('ACE-Step/ACE-Step-1.5', d)
    sh(['uv', 'sync'], cwd=d)
    print('acestep: готово (модели скачаются при первой генерации)')


def install_singer():
    d = ENGINES / 'SoulX-Singer'
    clone('Soul-AILab/SoulX-Singer', d)
    py = d / '.venv' / 'Scripts' / 'python.exe'
    if not py.exists():
        sh(['uv', 'venv', '-p', '3.10', '.venv'], cwd=d)
    sh(['uv', 'pip', 'install', '-p', py, 'torch==2.2.0', 'torchaudio==2.2.0', '--index-url',
        'https://download.pytorch.org/whl/cu121'], cwd=d)
    req = [line.strip() for line in (d / 'requirements.txt').read_text().splitlines()
           if line.strip() and not line.split('==')[0] in ('torch', 'torchaudio', 'torchcodec', 'sageattention',
                                                           'nemo_toolkit', 'wandb', 'funasr', 'webrtcvad')]
    (d / 'req_win.txt').write_text('\n'.join(req + ['webrtcvad-wheels', 'huggingface_hub[cli]']), encoding='utf-8')
    sh(['uv', 'pip', 'install', '-p', py, '-r', 'req_win.txt'], cwd=d)
    sh([py, '-c', "import nltk; nltk.download('averaged_perceptron_tagger_eng', quiet=True); nltk.download('cmudict', quiet=True)"])
    if not (d / 'pretrained_models/SoulX-Singer/model.pt').exists():
        sh([d / '.venv/Scripts/hf.exe', 'download', 'Soul-AILab/SoulX-Singer', '--local-dir',
            'pretrained_models/SoulX-Singer'], cwd=d)
    print('singer: готово')


def install_woosh():
    d = ENGINES / 'Woosh'
    clone('SonyResearch/Woosh', d)
    sh(['uv', 'sync', '--extra', 'cuda'], cwd=d)
    for z in WOOSH_ZIPS:
        if any((d / 'checkpoints' / z).glob('*.safetensors')):
            continue
        zp = d / f'{z}.zip'
        _download(f'https://github.com/SonyResearch/Woosh/releases/download/v1.0.0/{z}.zip', zp)
        with zipfile.ZipFile(zp) as zf:
            for m in zf.namelist():
                name = m.split('checkpoints/', 1)[-1]
                if not name or m.endswith('/'):
                    continue
                out = d / 'checkpoints' / name
                out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(m) as src, open(out, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
        zp.unlink()
    print('woosh: готово (веса CC-BY-NC — только некоммерческое использование)')


ENGINE_INSTALLERS = {'acestep': install_acestep, 'singer': install_singer, 'woosh': install_woosh}

if __name__ == '__main__':
    names = sys.argv[1:] or ['salamander', 'sso', 'musescore']
    if 'neural' in names:
        names = [n for n in names if n != 'neural'] + list(ENGINE_INSTALLERS)
    for n in names:
        if n in LIBS:
            install_lib(n)
        elif n in ENGINE_INSTALLERS:
            ENGINE_INSTALLERS[n]()
        else:
            print(f'не знаю {n!r}: {", ".join(list(LIBS) + list(ENGINE_INSTALLERS) + ["neural"])}')
