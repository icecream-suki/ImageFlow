"""Pillow provides composed RGBA frames; FFmpeg performs all output encoding."""
from pathlib import Path
from PIL import Image

from .models import Cancelled, FlowError


def fix_webp_final_duration(path: Path, duration: float):
    """Correct libwebp_anim's estimated final delay without re-encoding pixels.

    FFmpeg's libwebp encoder estimates the last frame's duration from average PTS
    deltas, ignoring a VFR source's final hold. ANMF's uint24 duration is container
    metadata (WebP RIFF specification). Preserve all compressed frame payloads.
    """
    with path.open("r+b") as stream:
        header = stream.read(12)
        if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WEBP":
            raise FlowError("输出不是有效的 WebP 容器。")
        end = int.from_bytes(header[4:8], "little") + 8
        offset, elapsed, last = 12, 0, None
        while offset + 8 <= end:
            stream.seek(offset)
            chunk = stream.read(8)
            if len(chunk) != 8:
                raise FlowError("WebP 输出不完整。")
            length = int.from_bytes(chunk[4:], "little")
            if offset + 8 + length > end:
                raise FlowError("WebP 帧数据越界。")
            if chunk[:4] == b"ANMF":
                if length < 16:
                    raise FlowError("WebP 动画帧头损坏。")
                stream.seek(offset + 8 + 12)
                delay = int.from_bytes(stream.read(3), "little")
                last = (offset + 8 + 12, elapsed)
                elapsed += delay
            offset += 8 + length + (length % 2)
        if last is None:
            return False  # libwebp may reduce an identical-frame animation to a still.
        delay = round(duration * 1000) - last[1]
        if not 1 <= delay <= 0xffffff:
            raise FlowError("WebP 最后一帧时长无法表示；请调整输出帧率。")
        stream.seek(last[0])
        stream.write(delay.to_bytes(3, "little"))
    return True


def normalize_animation(media, directory: Path, cancel, progress):
    """A private concat manifest avoids filename escaping and handles VFR timing.

    APNG default posters are excluded. Pillow applies GIF disposal/APNG blend and
    WebP composition. Only one RGBA frame is resident at a time.
    """
    entries = ["ffconcat version 1.0"]
    elapsed = 0.0
    with Image.open(media.path) as im:
        start = 1 if im.info.get("default_image", False) else 0
        for index, delay in enumerate(media.durations):
            if cancel.is_set():
                raise Cancelled("任务已取消。")
            im.seek(index + start)
            frame = im.convert("RGBA")
            name = f"frame{index:06d}.png"
            frame.save(directory / name, compress_level=1)
            entries += [f"file '{name}'", "option framerate 1000", f"duration {delay:.6f}"]
            elapsed += delay
            progress(min(20, int(20 * elapsed / media.duration)))
        # Sentinel establishes the exact end timestamp. -t removes it from output.
        entries += [f"file 'frame{len(media.durations)-1:06d}.png'", "option framerate 1000"]
    manifest = directory / "frames.ffconcat"
    manifest.write_text("\n".join(entries) + "\n", encoding="ascii")
    return ["-f", "concat", "-safe", "0", "-i", str(manifest)]
