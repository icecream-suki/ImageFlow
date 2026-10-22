"""Deterministic WebM preview benchmark; never reads user media."""
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from PIL import Image, ImageDraw
from imageflow.capabilities import inspect
from imageflow.process import capture
from imageflow.probe import probe
from imageflow.gui.preview import load_preview

root = Path(__file__).resolve().parent.parent / 'artifacts' / 'preview-benchmark'
root.mkdir(parents=True, exist_ok=True)
caps = inspect(os.environ['IMAGEFLOW_FFMPEG'], os.environ.get('IMAGEFLOW_FFPROBE', ''))
source = root / 'sample.webm'
if not source.exists():
    frames = []
    for i in range(60):
        im = Image.new('RGBA', (512, 512), (0, 0, 0, 0))
        draw = ImageDraw.Draw(im)
        for j in range(15):
            x, y = (i*7+j*23) % 450, (i*3+j*29) % 450
            draw.ellipse((x, y, x+60, y+60), fill=(30+j*14, 220-j*10, 160, 180+j*5))
        frames.append(im)
    apng = root / 'sample.apng'
    frames[0].save(apng, save_all=True, append_images=frames[1:], duration=50, loop=0)
    capture([caps.ffmpeg, '-y', '-v', 'error', '-ignore_loop', '1', '-i', str(apng), '-t', '3',
             '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p', '-auto-alt-ref', '0', str(source)], timeout=90)
media = probe(source, caps.ffprobe)
results = []
for _ in range(3):
    started = time.perf_counter()
    if '--after' in sys.argv:
        first = []
        data = load_preview(media, caps, on_first=lambda _: first.append(time.perf_counter()-started))
    else:
        first = []
        data = load_preview(media, caps)
    elapsed = time.perf_counter()-started
    results.append({'first_frame_seconds': first[0] if first else elapsed, 'total_seconds': elapsed,
                    'frames': len(data.frames)})
label = 'after' if '--after' in sys.argv else 'before'
(root / f'{label}.json').write_text(json.dumps(results, indent=2), 'utf-8')
print(json.dumps({label: results}, indent=2))
