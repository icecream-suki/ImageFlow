from dataclasses import replace
from pathlib import Path
import hashlib
import threading
import time

import pytest
from PIL import Image

from imageflow.engine import Engine
from imageflow.models import Options, Task, State, FlowError
from imageflow.probe import probe
from imageflow.process import capture
from imageflow.queue import TaskQueue

pytestmark = pytest.mark.integration


def convert(caps, source, out, **kwargs):
    task = Task(probe(source, caps.ffprobe), Options(**kwargs), out)
    Engine(caps).execute(task)
    assert task.state == State.DONE, task.log
    return task


def test_ffmpeg_detection(caps):
    assert "ffmpeg version" in caps.version
    assert "ffprobe version" in caps.probe_version
    for fmt in ["png", "jpeg", "webp", "bmp", "tiff", "gif", "apng"]:
        caps.require(fmt)


def test_static_webp_png_alpha(caps, samples, tmp_path):
    task = convert(caps, samples["webp"], tmp_path / "out")
    with Image.open(task.output) as image:
        assert image.size == (64, 48)
        assert image.convert("RGBA").getpixel((0, 0))[3] == 0
        assert image.convert("RGBA").getpixel((5, 36))[3] == 128
        assert image.convert("RGBA").getpixel((10, 10)) == samples["frames"][0].getpixel((10, 10))


def test_jpeg_background(caps, samples, tmp_path):
    task = convert(caps, samples["png"], tmp_path / "out", format="jpeg", background="#3366cc", quality=100)
    with Image.open(task.output) as image:
        pixel = image.convert("RGB").getpixel((0, 0))
        assert all(abs(a-b) <= 5 for a, b in zip(pixel, (51, 102, 204)))


@pytest.mark.parametrize("fmt", ["png", "jpeg", "webp", "bmp", "tiff"])
def test_static_outputs(caps, samples, tmp_path, fmt):
    task = convert(caps, samples["png"], tmp_path / fmt, format=fmt, lossless_webp=True)
    with Image.open(task.output) as image:
        assert image.size == (64, 48)


@pytest.mark.parametrize("source", ["gif", "animated_webp", "apng"])
@pytest.mark.parametrize("fmt", ["gif", "webp", "apng"])
def test_animation_matrix(caps, samples, tmp_path, source, fmt):
    task = convert(caps, samples[source], tmp_path / (source + fmt), format=fmt, lossless_webp=True)
    output = probe(task.output, caps.ffprobe)
    assert output.animated
    assert output.frames == 4
    assert output.duration == pytest.approx(.7, abs=.03), (output.durations, task.log)
    assert output.alpha is True
    with Image.open(task.output) as image:
        for index in range(4):
            image.seek(index)
            rgba = image.convert("RGBA")
            assert rgba.getpixel((0, 0))[3] == 0
            assert rgba.getpixel((10+index*6, 10))[3] == 255


def test_fps_retains_duration_and_order(caps, samples, tmp_path):
    task = convert(caps, samples["animated_webp"], tmp_path / "out", format="gif", fps=20)
    output = probe(task.output, caps.ffprobe)
    assert output.duration == pytest.approx(.7, abs=.06)
    with Image.open(task.output) as image:
        image.seek(image.n_frames-1)
        assert image.convert("RGBA").getpixel((30, 10))[3] == 255


def test_edit_pipeline(caps, samples, tmp_path):
    task = convert(caps, samples["png"], tmp_path / "out", crop=(8, 8, 32, 24), resize="percent", percent=50,
                   rotation=90, hflip=True, vflip=True)
    assert Image.open(task.output).size == (12, 16)
    arbitrary = convert(caps, samples["png"], tmp_path / "rotated", rotation=45)
    assert Image.open(arbitrary.output).width > 64


def test_batch_telegram_and_input_safety(caps, samples, tmp_path):
    sources = [samples["png"], samples["webp"], samples["animated_webp"], samples["gif"]]
    hashes = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    engine = Engine(caps)
    queue = TaskQueue(engine, concurrency=2)
    for source in sources:
        queue.add(Task(probe(source, caps.ffprobe), Options(telegram=True), source.parent))
    try:
        queue.start()
        for future in queue.futures.values():
            future.result(timeout=30)
        assert all(t.state == State.DONE for t in queue.tasks), [t.log for t in queue.tasks]
        assert [t.output.suffix for t in queue.tasks] == [".png", ".png", ".gif", ".gif"]
        assert all(hashlib.sha256(p.read_bytes()).hexdigest() == hashes[p] for p in sources)
    finally:
        queue.shutdown()


def test_failed_task_does_not_block_and_retry(caps, samples, tmp_path):
    broken_caps = replace(caps, ffmpeg=str(tmp_path / "missing.exe"))
    queue = TaskQueue(Engine(broken_caps), 1)
    task = Task(probe(samples["png"], caps.ffprobe), Options(), tmp_path / "out")
    queue.add(task)
    try:
        queue.start()
        for future in queue.futures.values():
            future.result(timeout=10)
        assert task.state == State.FAILED and task.error
        assert not list((tmp_path / "out").glob(".imageflow-*"))
        queue.engine.caps = caps
        queue.retry_failed()
        for future in queue.futures.values():
            future.result(timeout=10)
        assert task.state == State.DONE
    finally:
        queue.shutdown()


def test_cancel_before_start(caps, samples, tmp_path):
    task = Task(probe(samples["png"], caps.ffprobe), Options(), tmp_path / "out")
    task.cancel.set()
    Engine(caps).execute(task)
    assert task.state == State.CANCELLED
    assert not (tmp_path / "out").exists()


def test_webm_alpha_sticker(caps, samples, tmp_path):
    if "libvpx-vp9" not in caps.encoders or "libvpx-vp9" not in caps.decoders:
        pytest.skip("此构建没有 VP9 Alpha 编解码器")
    webm = tmp_path / "透明 sticker.webm"
    capture([caps.ffmpeg, "-y", "-v", "error", "-loop", "1", "-i", str(samples["png"]), "-t", "0.6",
             "-vf", "fps=10", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", str(webm)])
    source = probe(webm, caps.ffprobe)
    assert source.alpha is True
    for fmt in ["gif", "apng", "webp"]:
        task = convert(caps, webm, tmp_path / fmt, format=fmt, lossless_webp=True)
        with Image.open(task.output) as image:
            assert image.convert("RGBA").getpixel((0, 0))[3] == 0
            assert image.convert("RGBA").getpixel((10, 10))[3] > 240


def test_first_frame_is_explicit(caps, samples, tmp_path):
    task = Task(probe(samples["gif"], caps.ffprobe), Options(), tmp_path / "out")
    Engine(caps).execute(task)
    assert task.state == State.FAILED and "首帧" in task.error
    converted = convert(caps, samples["gif"], tmp_path / "out", allow_first_frame=True)
    assert not probe(converted.output, caps.ffprobe).animated


def test_missing_alpha_decoder_is_rejected(caps, samples, tmp_path):
    media = replace(probe(samples["png"], caps.ffprobe), format="WEBM", animated=True,
                    codec="vp9", alpha=True, duration=.5, fps=10)
    limited = replace(caps, decoders=caps.decoders - {"libvpx-vp9"})
    task = Task(media, Options(format="gif"), tmp_path / "out")
    Engine(limited).execute(task)
    assert task.state == State.FAILED
    assert "libvpx-vp9" in task.error
    assert not list((tmp_path / "out").glob("*.gif"))


def test_real_ffmpeg_cancellation(caps, samples):
    from imageflow.process import run
    from imageflow.models import Cancelled
    cancel = threading.Event()
    timer = threading.Timer(.5, cancel.set)
    timer.start()
    try:
        with pytest.raises(Cancelled):
            run([caps.ffmpeg, "-hide_banner", "-nostdin", "-re", "-loop", "1", "-i", str(samples["png"]),
                 "-t", "30", "-f", "null", "-"], cancel)
    finally:
        timer.join()


def test_folder_structure_skip_and_overwrite(caps, samples, tmp_path):
    root = tmp_path / "input"
    nested = root / "子目录"
    nested.mkdir(parents=True)
    source = nested / "same.webp"
    source.write_bytes(samples["webp"].read_bytes())
    output = tmp_path / "out"
    media = probe(source, caps.ffprobe)
    engine = Engine(caps)
    task = Task(media, Options(preserve_structure=True), output, root)
    engine.execute(task)
    assert task.output == output / "子目录" / "same.png"
    original_output = task.output.read_bytes()
    skipped = Task(media, Options(conflict="skip", preserve_structure=True), output, root)
    engine.execute(skipped)
    assert skipped.state == State.SKIPPED
    assert task.output.read_bytes() == original_output
    overwritten = Task(media, Options(conflict="overwrite", preserve_structure=True, rotation=90), output, root)
    engine.execute(overwritten)
    assert overwritten.state == State.DONE
    assert Image.open(overwritten.output).size == (48, 64)
    assert source.read_bytes() == samples["webp"].read_bytes()


def test_apng_default_poster_excluded(caps, samples, tmp_path):
    poster = Image.new("RGBA", (64, 48), (0, 255, 0, 255))
    source = tmp_path / "poster.png"
    poster.save(source, save_all=True, append_images=samples["frames"], default_image=True,
                duration=[100, 200, 100, 300], loop=0, disposal=0, blend=0)
    info = probe(source, caps.ffprobe)
    assert info.frames == 4 and info.duration == pytest.approx(.7)
    task = convert(caps, source, tmp_path / "out", format="apng")
    with Image.open(task.output) as image:
        assert image.convert("RGBA").getpixel((0, 0))[3] == 0


def test_gif_size_limit_is_enforced(caps, tmp_path):
    import random
    rng = random.Random(31)
    frames = [Image.frombytes("RGB", (256, 256), rng.randbytes(256*256*3)) for _ in range(8)]
    source = tmp_path / "noise.apng"
    frames[0].save(source, save_all=True, append_images=frames[1:], duration=100, loop=0)
    task = Task(probe(source, caps.ffprobe), Options(format="gif", gif_limit_kb=1), tmp_path / "out")
    Engine(caps).execute(task)
    assert task.state == State.FAILED
    assert "体积限制" in task.error
    assert not list((tmp_path / "out").glob("*.gif"))
    assert not list((tmp_path / "out").glob(".imageflow-*"))


def test_loop_semantics(caps, samples, tmp_path):
    for fmt in ["gif", "webp", "apng"]:
        for plays in [0, 1, 3]:
            task = convert(caps, samples["animated_webp"], tmp_path / f"{fmt}-{plays}", format=fmt, loops=plays)
            with Image.open(task.output) as image:
                actual = image.info.get("loop")
                expected = (None if plays == 1 else 0 if plays == 0 else plays-1) if fmt == "gif" else plays
                assert actual == expected, (fmt, plays, actual, task.log)


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "BMP", "TIFF", "GIF"])
def test_all_static_input_formats(caps, samples, tmp_path, fmt):
    source = tmp_path / ("input." + fmt.lower())
    samples["frames"][0].convert("RGB").save(source, format=fmt)
    task = convert(caps, source, tmp_path / "out")
    assert Image.open(task.output).size == (64, 48)


def test_failed_task_does_not_block_next(caps, samples, tmp_path):
    media = probe(samples["png"], caps.ffprobe)
    queue = TaskQueue(Engine(caps), 1)
    first = Task(media, Options(crop=(0, 0, 500, 500)), tmp_path / "out")
    second = Task(media, Options(), tmp_path / "out")
    queue.add(first)
    queue.add(second)
    try:
        queue.start()
        for future in queue.futures.values():
            future.result(timeout=15)
        assert first.state == State.FAILED
        assert second.state == State.DONE
    finally:
        queue.shutdown()


def test_cancel_queued_tasks(caps, samples, tmp_path):
    queue = TaskQueue(Engine(caps), 1)
    for _ in range(3):
        queue.add(Task(probe(samples["png"], caps.ffprobe), Options(), tmp_path / "out"))
    queue.cancel_waiting()
    queue.start()
    assert not queue.active
    assert all(task.state == State.CANCELLED for task in queue.tasks)
    assert not (tmp_path / "out").exists()
    queue.shutdown()
