from fractions import Fraction
from pathlib import Path
import json
import warnings

from PIL import Image

from .models import FlowError, MediaInfo
from .process import capture


EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".apng", ".webm", ".tgs"}
RASTER_FORMATS = {"PNG", "JPEG", "WEBP", "BMP", "TIFF", "GIF"}
MAX_PIXELS = 80_000_000
MAX_FRAMES = 10000


def scan_inputs(paths, recursive=False, extensions=None):
    """Return (file, import root) pairs; never traverse directory symlinks."""
    selected = set(extensions or EXTENSIONS)
    seen = set()
    found = []
    for value in paths:
        path = Path(value).resolve()
        candidates = path.rglob("*") if path.is_dir() and recursive else path.iterdir() if path.is_dir() else [path]
        for item in candidates:
            if item.is_file() and not item.is_symlink() and item.suffix.lower() in selected:
                resolved = item.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    found.append((resolved, path if path.is_dir() else path.parent))
    return sorted(found, key=lambda pair: str(pair[0]).casefold())


def _number(value):
    try:
        result = float(Fraction(str(value)))
        return result if result > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def probe(path, ffprobe):
    path = Path(path).resolve()
    if path.suffix.lower() == ".tgs":
        raise FlowError("TGS 是 gzip/Lottie 矢量动画，FFmpeg 不能原生解码。第一版暂不支持，需要额外的本地 Lottie 渲染引擎。")
    if not path.is_file():
        raise FlowError("输入文件不存在。")
    if path.suffix.lower() not in EXTENSIONS:
        raise FlowError("仅支持图片和 Telegram WebM 贴纸。")
    data = {}
    probe_warning = ""
    try:
        data = json.loads(capture([ffprobe, "-v", "error",
                                   "-show_streams", "-show_format", "-of", "json", str(path)], timeout=30))
    except (FlowError, ValueError) as exc:
        probe_warning = f"FFprobe 未能完整识别，使用 Pillow 信息：{exc}"
    streams = data.get("streams", [])
    stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    codec = stream.get("codec_name", "")
    if path.suffix.lower() == ".webm":
        # A deliberately narrow input gate: this application is not a video converter.
        duration = _number(stream.get("duration")) or _number(data.get("format", {}).get("duration"))
        width, height = stream.get("width", 0), stream.get("height", 0)
        container = data.get("format", {}).get("format_name", "")
        if "webm" not in container or codec not in {"vp8", "vp9"} or not duration or duration > 3.1 or max(width, height) > 512 or min(width, height) < 1:
            raise FlowError("只接受 VP8/VP9 WebM 贴纸输入（最长约 3 秒、宽高不超过 512），不支持普通视频。")
        # Probe all streams to reject audio, which is outside sticker scope.
        if any(s.get("codec_type") == "audio" for s in streams):
            raise FlowError("WebM 贴纸不能包含音频。")
        alpha_tag = {str(k).lower(): str(v) for k, v in stream.get("tags", {}).items()}.get("alpha_mode")
        alpha = True if alpha_tag == "1" or "a" in stream.get("pix_fmt", "").replace("gray", "") else None
        return MediaInfo(path, "WEBM", width, height, animated=True, duration=duration,
                         fps=_number(stream.get("avg_frame_rate")) or _number(stream.get("r_frame_rate")),
                         alpha=alpha, codec=codec)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as im:
                if im.format not in RASTER_FORMATS:
                    raise FlowError("文件内容不是受支持的图片。")
                if im.width * im.height > MAX_PIXELS:
                    raise FlowError("单帧超过 8000 万像素，已阻止处理以避免内存耗尽。")
                count = getattr(im, "n_frames", 1)
                if count > MAX_FRAMES:
                    raise FlowError("动画超过 10000 帧，请先拆分。")
                default = 1 if im.info.get("default_image", False) else 0
                count -= default
                is_animation = count > 1 and im.format in {"GIF", "WEBP", "PNG"}
                notes = [probe_warning] if probe_warning else []
                if im.format == "TIFF" and count > 1:
                    raise FlowError("多页 TIFF 暂不支持；请先拆分页面，避免静默丢失页面。")
                durations = []
                alpha = False
                for i in range(default, count + default):
                    im.seek(i)
                    rgba = im.convert("RGBA")  # also forces WebP's timestamp/duration update
                    alpha |= rgba.getextrema()[3][0] < 255
                    if is_animation:
                        delay = im.info.get("duration")
                        if delay is None or delay <= 0:
                            delay = 100
                            if "部分帧未声明有效延时，按 100ms 显示和转换。" not in notes:
                                notes.append("部分帧未声明有效延时，按 100ms 显示和转换。")
                        durations.append(float(delay) / 1000)
                width = stream.get("width") or im.width
                height = stream.get("height") or im.height
                # Pillow's composited frames are the source for animation normalization.
                if is_animation:
                    width, height = im.size
                duration = sum(durations) if durations else None
                return MediaInfo(path, "APNG" if im.format == "PNG" and is_animation else im.format,
                                 width, height, count, is_animation, duration,
                                 count / duration if duration else None, alpha, codec, durations, notes)
    except FlowError:
        raise
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise FlowError(f"无法读取图片，文件可能损坏或格式不受支持：{exc}") from exc
