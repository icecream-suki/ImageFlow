import sys
import threading
import time
from dataclasses import replace

import pytest
from PIL import Image

from imageflow.gui.preview import load_preview, PreviewCache, PreviewData
from imageflow.models import Cancelled, FlowError
from imageflow.process import capture, stream_frames
from imageflow.probe import probe


@pytest.mark.integration
def test_raw_preview_alpha_timing_and_first_frame(caps, samples, tmp_path):
    webm = tmp_path / "透明 sticker.webm"
    capture([caps.ffmpeg, "-y", "-v", "error", "-i", str(samples["apng"]), "-t", "0.7",
             "-vf", "fps=10", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", str(webm)])
    media = probe(webm, caps.ffprobe)
    first = []
    data = load_preview(media, caps, on_first=lambda d: first.append(d))
    assert len(first) == 1 and len(first[0].frames) == 1
    assert len(data.frames) == 7
    assert sum(data.delays) == pytest.approx(media.duration * 1000, abs=110)
    image = Image.frombytes("RGBA", data.frame_size, data.frames[0])
    assert image.getpixel((0, 0))[3] == 0 and image.getpixel((12, 12))[3] > 240
    assert data.frames[0] != data.frames[-1]
    cancel = threading.Event()
    with pytest.raises(Cancelled):
        load_preview(media, caps, cancel, lambda _: cancel.set())


@pytest.mark.integration
def test_pillow_raw_preview_timing_and_cache_bounds(caps, samples):
    media = probe(samples["animated_webp"], caps.ffprobe)
    data = load_preview(media, caps)
    assert data.delays == [100, 200, 100, 300]
    assert Image.frombytes("RGBA", data.frame_size, data.frames[0]).getpixel((0, 0))[3] == 0
    cache = PreviewCache(budget=sum(map(len, data.frames)))
    key = cache.key(media, caps)
    cache.put(key, data)
    assert cache.get(key) is data
    cache.put("second", data)
    assert cache.get(key) is None and cache.get("second") is data
    media.path.write_bytes(media.path.read_bytes() + b"trailing")
    assert cache.key(media, caps) != key


def test_stalled_preview_process_cancels_promptly():
    cancel = threading.Event()
    timer = threading.Timer(.3, cancel.set)
    timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(Cancelled):
            stream_frames([sys.executable, "-c", "import time; time.sleep(30)"], 4, cancel, lambda _: None)
        assert time.monotonic() - started < 8
    finally:
        timer.join()


def test_partial_raw_frame_is_rejected():
    with pytest.raises(FlowError, match="不完整帧"):
        stream_frames([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'xx')"],
                      4, threading.Event(), lambda _: None)
