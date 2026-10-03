"""Runs inside the Woosh venv. Text → sound effect (Sony AI Woosh, CC-BY-NC weights: non-commercial use).

Job JSON: {"items": [{"prompt": "claws scraping a stone wall", "duration": 5, "seed": 1, "out": "C:/.../x.wav"}],
           "model": "fast" | "quality", "steps": 4, "cfg": 4.5}
Several items in one job share the loaded model. Output: stereo? — the autoencoder decides; 48 kHz WAV.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / 'Woosh'
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
FRAMES_PER_SEC = 100.0            # 501 latent frames = 5 s (checked by rendering)


def main(job_path):
    import torch
    import torchaudio
    from woosh.components.base import LoadConfig
    job = json.loads(Path(job_path).read_text(encoding='utf-8'))
    fast = job.get('model', 'fast') == 'fast'
    if fast:
        from woosh.inference.flowmap_sampler import sample_euler
        from woosh.model.flowmap_from_pretrained import FlowMapFromPretrained
        ldm = FlowMapFromPretrained(LoadConfig(path='checkpoints/Woosh-DFlow')).eval().to('cuda')
    else:
        from woosh.inference.flowmatching_sampler import flowmatching_integrate
        from woosh.model.ldm import LatentDiffusionModel
        ldm = LatentDiffusionModel(LoadConfig(path='checkpoints/Woosh-Flow')).eval().to('cuda')
    for it in job['items']:
        torch.manual_seed(int(it.get('seed', 0)))
        frames = max(50, min(2001, int(float(it.get('duration', 5)) * FRAMES_PER_SEC) + 1))
        noise = torch.randn(1, 128, frames).to('cuda')
        cond = ldm.get_cond({'audio': None, 'description': [it['prompt']]}, no_dropout=True, device='cuda')
        with torch.inference_mode():
            if fast:
                steps = int(job.get('steps', 4))
                renoise = [0, 0.5, 0.5, 0.3][:steps] + [0.3] * max(0, steps - 4)
                x = sample_euler(model=ldm, noise=noise, cond=cond, num_steps=steps, renoise=renoise,
                                 cfg=float(job.get('cfg', 4.5)))
            else:
                x = flowmatching_integrate(ldm, noise=noise, cond=cond, cfg=float(job.get('cfg', 4.5)), atol=0.001,
                                           rtol=0.001, device='cuda', dtype=torch.float64)
            audio = ldm.autoencoder.inverse(x).cpu()[0]
        peak = float(audio.abs().max())
        audio = audio / max(peak, 1.0)
        torchaudio.save(it['out'], audio.float(), sample_rate=48000)
        print('OK', it['out'])


if __name__ == '__main__':
    main(sys.argv[1])
