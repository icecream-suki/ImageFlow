from dataclasses import dataclass, field
from pathlib import Path
from enum import StrEnum
import math
import re
import threading
import uuid


class FlowError(Exception):
    """An actionable error suitable for the GUI."""


class Cancelled(FlowError):
    pass


class State(StrEnum):
    WAITING = "等待中"
    RUNNING = "处理中"
    DONE = "已完成"
    FAILED = "失败"
    CANCELLED = "已取消"
    SKIPPED = "已跳过"


@dataclass
class MediaInfo:
    path: Path
    format: str
    width: int
    height: int
    frames: int | None = None
    animated: bool = False
    duration: float | None = None
    fps: float | None = None
    alpha: bool | None = None
    codec: str = ""
    durations: list[float] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def size(self):
        return self.path.stat().st_size

    @property
    def recommendation(self):
        if self.animated:
            return "建议 GIF 优化、动态 WebP 或 APNG"
        return "建议 PNG（无损编码）或 WebP（体积优化）"


@dataclass
class Options:
    format: str = "png"
    telegram: bool = False
    telegram_animation: str = "gif"
    resize: str = "original"  # original / fit / exact / percent
    width: int = 512
    height: int = 512
    percent: float = 100.0
    only_shrink: bool = True
    interpolation: str = "lanczos"
    crop: tuple[int, int, int, int] | None = None  # x,y,w,h in original coordinates
    rotation: float = 0
    hflip: bool = False
    vflip: bool = False
    quality: int = 85
    lossless_webp: bool = False
    strip_metadata: bool = True
    preserve_alpha: bool = True
    background: str = "#ffffff"
    fps: float | None = None
    loops: int = 0  # total plays; 0 = infinite
    colors: int = 256
    dither: str = "sierra2_4a"
    alpha_threshold: int = 128
    gif_limit_kb: int = 0
    allow_first_frame: bool = False
    conflict: str = "rename"
    preserve_structure: bool = False
    # Keep the original explicit-format API for callers; GUI uses ordered routing.
    auto_route: bool = False
    image_format: str = "png"
    animation_format: str = "gif"
    routing_rules: list[dict] = field(default_factory=list)

    def output_format(self, media: MediaInfo):
        if self.auto_route:
            from .routing import resolve_output
            return resolve_output(media, self.image_format, self.animation_format, self.routing_rules)[0]
        return (self.telegram_animation if media.animated else "png") if self.telegram else self.format

    def validate(self, media: MediaInfo):
        fmt = self.output_format(media)
        if fmt not in {"png", "jpeg", "webp", "bmp", "tiff", "gif", "apng"}:
            raise FlowError("不支持的输出格式。")
        if self.resize not in {"original", "fit", "exact", "percent"}:
            raise FlowError("无效的缩放模式。")
        if not 1 <= self.width <= 32768 or not 1 <= self.height <= 32768:
            raise FlowError("输出宽高必须在 1–32768 之间。")
        if not math.isfinite(self.percent) or not 0 < self.percent <= 1000:
            raise FlowError("缩放百分比必须在 0–1000 之间。")
        if self.interpolation not in {"lanczos", "bicubic", "bilinear", "neighbor"}:
            raise FlowError("无效的缩放算法。")
        if not math.isfinite(self.rotation) or not -360 <= self.rotation <= 360:
            raise FlowError("旋转角度必须在 -360–360 之间。")
        if not 1 <= self.quality <= 100 or not 4 <= self.colors <= 256:
            raise FlowError("质量或 GIF 颜色数无效。")
        if self.fps is not None and (not math.isfinite(self.fps) or not 1 <= self.fps <= 60):
            raise FlowError("动画帧率必须在 1–60 fps 之间。")
        if not 0 <= self.loops <= 65535 or not 0 <= self.alpha_threshold <= 255:
            raise FlowError("循环次数或透明度阈值无效。")
        if self.dither not in {"sierra2_4a", "bayer", "floyd_steinberg", "none"}:
            raise FlowError("不支持的抖动算法。")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", self.background):
            raise FlowError("背景色必须为 #RRGGBB。")
        if self.conflict not in {"rename", "skip", "overwrite"} or self.gif_limit_kb < 0:
            raise FlowError("重名策略或体积限制无效。")
        if self.crop:
            x, y, w, h = self.crop
            if min(x, y) < 0 or min(w, h) <= 0 or x+w > media.width or y+h > media.height:
                raise FlowError(f"裁剪区域超出原图 {media.width}×{media.height}；坐标以原图为准。")
        if media.animated and fmt in {"png", "jpeg", "bmp", "tiff"} and not self.allow_first_frame:
            raise FlowError("此输出格式只保留首帧。请明确勾选「允许动画仅导出首帧」。")


@dataclass
class Task:
    media: MediaInfo
    options: Options
    output_dir: Path
    source_root: Path | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state: State = State.WAITING
    progress: int = 0
    output: Path | None = None
    error: str = ""
    log: str = ""
    output_size: int = 0
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)
