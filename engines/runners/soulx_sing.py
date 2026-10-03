"""Runs inside the SoulX-Singer venv. Sings a note list with a real singing voice (score control).

Job JSON: {"notes": [{"start": s, "dur": s, "midi": 64, "syl": "la", "lang": "en|ru|ja|zh"}], "voice": "en_female",
           "out": "C:/.../vocal.wav", "pitch_shift": 0, "steps": 32, "cfg": 3.0}
Syllables: English words/syllables (g2p), Cyrillic («ля», «ки» — also kana converted by Sound Lab), romaji (lang ja),
pinyin with tone (lang zh, «ni3»). "-" as syllable = melisma (holds the previous syllable on a new pitch).
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / 'SoulX-Singer'
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

VOICES = {
    'en_female': ('example/audio/en_prompt.mp3', 'example/audio/en_prompt.json'),
    'zh_female': ('example/audio/zh_prompt.mp3', 'example/audio/zh_prompt.json'),
    'zh_male': ('example/audio/zh_target.mp3', 'example/audio/zh_target.json'),
    'yue_voice': ('example/audio/yue_target.mp3', 'example/audio/yue_target.json'),
}
VOW = {'a': 'AA1', 'i': 'IY1', 'u': 'UW1', 'e': 'EH1', 'o': 'OW1', 'y': 'IH1',
       'а': 'AA1', 'и': 'IY1', 'у': 'UW1', 'э': 'EH1', 'о': 'OW1', 'ы': 'IH1'}
IOT = {'я': 'AA1', 'ю': 'UW1', 'ё': 'OW1', 'е': 'EH1'}
CONS = {'б': ['B'], 'в': ['V'], 'г': ['G'], 'д': ['D'], 'ж': ['ZH'], 'з': ['Z'], 'й': ['Y'], 'к': ['K'], 'л': ['L'],
        'м': ['M'], 'н': ['N'], 'п': ['P'], 'р': ['R'], 'с': ['S'], 'т': ['T'], 'ф': ['F'], 'х': ['HH'], 'ц': ['T', 'S'],
        'ч': ['CH'], 'ш': ['SH'], 'щ': ['SH'],
        'b': ['B'], 'v': ['V'], 'g': ['G'], 'd': ['D'], 'j': ['JH'], 'z': ['Z'], 'k': ['K'], 'l': ['L'], 'm': ['M'],
        'n': ['N'], 'p': ['P'], 'r': ['R'], 's': ['S'], 't': ['T'], 'f': ['F'], 'h': ['HH'], 'w': ['W'],
        'ch': ['CH'], 'sh': ['SH'], 'ts': ['T', 'S'], 'ky': ['K', 'Y'], 'ny': ['N', 'Y'], 'ry': ['R', 'Y']}
_g2p = None


def cyr_or_romaji(s):
    """«ля» / «ки» / «tsu» → ARPAbet phones."""
    s = s.lower().strip('.,!?…')
    out = []
    i = 0
    while i < len(s):
        c2, c = s[i:i + 2], s[i]
        if c2 in CONS and len(c2) == 2:
            out += CONS[c2]
            i += 2
        elif c in IOT:
            if not out or out[-1] in VOW.values() or out[-1] in IOT.values():
                out.append('Y')
            out.append(IOT[c])
            i += 1
        elif c in VOW:
            out.append(VOW[c])
            i += 1
        elif c in CONS:
            out += CONS[c]
            i += 1
        else:
            i += 1                                                    # ь ъ ' and unknown
    return out or ['AA1']


def english(word):
    global _g2p
    if _g2p is None:
        from g2p_en import G2p
        _g2p = G2p()
    phones = [p for p in _g2p(word) if re.fullmatch(r'[A-Z]+[012]?', p)]
    return phones or ['AA1']


def phonemes(syl, lang, phoneset):
    if lang == 'zh':
        p = f'zh_{syl.lower()}'
        return p if p in phoneset else 'zh_a1'
    if lang == 'en' and not re.search('[а-яё]', syl.lower()):
        ph = english(syl)
    else:
        ph = cyr_or_romaji(syl)
    ph = [p if f'en_{p}' in phoneset else (p.rstrip('012') + '1' if f'en_{p.rstrip("012")}1' in phoneset else p.rstrip('012'))
          for p in ph]
    ph = [p for p in ph if f'en_{p}' in phoneset] or ['AA1']
    return 'en_' + '-'.join(ph)


def segments(notes, max_len=14.0, gap=0.35):
    segs, cur = [], []
    for n in sorted(notes, key=lambda n: n['start']):
        if cur:
            end = cur[-1]['start'] + cur[-1]['dur']
            if n['start'] - end > gap or n['start'] + n['dur'] - cur[0]['start'] > max_len:
                segs.append(cur)
                cur = []
        cur.append(n)
    if cur:
        segs.append(cur)
    return segs


def build_meta(seg, phoneset, lang_default):
    pad = 0.12
    t0 = max(0.0, seg[0]['start'] - pad)
    text, ph, pitch, typ, dur = ['<SP>'], ['<SP>'], [0], [1], [round(seg[0]['start'] - t0, 3)]
    t = seg[0]['start']
    prev_ph, prev_text = None, None
    for n in seg:
        if n['start'] - t > 0.02:
            text.append('<SP>'); ph.append('<SP>'); pitch.append(0); typ.append(1); dur.append(round(n['start'] - t, 3))
        syl = str(n.get('syl') or 'a')
        if syl in ('-', '~', '_') and prev_ph:
            text.append(prev_text); ph.append(prev_ph); typ.append(3)
        else:
            prev_ph = phonemes(syl, n.get('lang') or lang_default, phoneset)
            prev_text = syl
            text.append(syl); ph.append(prev_ph); typ.append(2)
        pitch.append(int(round(n['midi'])))
        dur.append(round(n['dur'], 3))
        t = n['start'] + n['dur']
    text.append('<SP>'); ph.append('<SP>'); pitch.append(0); typ.append(1); dur.append(pad)
    end = t + pad
    lang_name = 'Mandarin' if lang_default == 'zh' else 'English'
    return {'index': f'seg_{int(t0 * 1000)}', 'language': lang_name, 'time': [int(t0 * 1000), int(end * 1000)],
            'duration': ' '.join(f'{d:.3f}' for d in dur), 'text': ' '.join(text), 'phoneme': ' '.join(ph),
            'note_pitch': ' '.join(map(str, pitch)), 'note_type': ' '.join(map(str, typ))}


def main(job_path):
    job = json.loads(Path(job_path).read_text(encoding='utf-8'))
    import numpy as np
    import soundfile as sf
    import torch
    from cli.inference import build_model
    from soulxsinger.utils.data_processor import DataProcessor
    from soulxsinger.utils.file_utils import load_config

    phoneset = set(json.loads(Path('soulxsinger/utils/phoneme/phone_set.json').read_text(encoding='utf-8')))
    voice = job.get('voice', 'en_female')
    if isinstance(voice, dict):
        prompt_wav, prompt_json = voice['wav'], voice['json']
    else:
        prompt_wav, prompt_json = VOICES.get(voice, VOICES['en_female'])
    config = load_config('soulxsinger/config/soulxsinger.yaml')
    config.infer.n_steps = int(job.get('steps', config.infer.n_steps))
    config.infer.cfg = float(job.get('cfg', config.infer.cfg))
    model = build_model('pretrained_models/SoulX-Singer/model.pt', config, 'cuda', use_fp16=True)
    dp = DataProcessor(hop_size=config.audio.hop_size, sample_rate=config.audio.sample_rate,
                       phoneset_path='soulxsinger/utils/phoneme/phone_set.json', device='cuda')
    prompt_meta = json.loads(Path(prompt_json).read_text(encoding='utf-8'))[0]
    prompt = dp.process(prompt_meta, prompt_wav)
    lang = job.get('lang', 'en')
    sr = config.audio.sample_rate
    parts = job.get('parts') or [{'notes': job['notes'],
                                  'takes': job.get('takes') or [{'seed': int(job.get('seed', 0)), 'out': job['out']}]}]
    for part in parts:                                   # one model load, many voice lines / takes
        metas = [build_meta(sg, phoneset, part.get('lang', lang)) for sg in segments(part['notes'])]
        total = int(metas[-1]['time'][1] / 1000 * sr) + sr
        targets = [dp.process(m, None) for m in metas]
        for take in part['takes']:
            torch.manual_seed(int(take['seed']))
            out = np.zeros(total, np.float32)
            for m, target in zip(metas, targets):
                with torch.no_grad():
                    audio = model.infer({'prompt': prompt, 'target': target},
                                        auto_shift=bool(job.get('auto_shift', False)),
                                        pitch_shift=int(job.get('pitch_shift', 0)), n_steps=config.infer.n_steps,
                                        cfg=config.infer.cfg, control='score', use_fp16=True)
                a = audio.squeeze().float().cpu().numpy()
                st = int(m['time'][0] / 1000 * sr)
                n = min(len(a), total - st)
                out[st:st + n] += a[:n]
            sf.write(take['out'], out, sr)
            print('OK', take['out'])


if __name__ == '__main__':
    main(sys.argv[1])
