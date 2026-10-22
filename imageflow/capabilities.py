from dataclasses import dataclass
from pathlib import Path
import re
import shutil

from .models import FlowError
from .process import capture


ENCODERS = {"png": "png", "jpeg": "mjpeg", "bmp": "bmp", "tiff": "tiff",
            "webp": "libwebp", "gif": "gif", "apng": "apng"}
MUXERS = {"png": "image2", "jpeg": "image2", "bmp": "image2", "tiff": "image2",
          "webp": "webp", "gif": "gif", "apng": "apng"}


def resolve_executable(value, name):
    if not value.strip():
        raise FlowError(f"请在设置中选择 {name} 可执行文件。")
    candidate = Path(value.strip().strip('"')).expanduser()
    if not candidate.is_file():
        found = shutil.which(str(candidate))
        if not found:
            raise FlowError(f"{name} 路径不存在：{value}。请重新选择。")
        candidate = Path(found)
    return str(candidate.resolve())


def find_tools():
    ffmpeg = shutil.which("ffmpeg") or ""
    return ffmpeg, sibling_probe(ffmpeg) or shutil.which("ffprobe") or ""


def sibling_probe(ffmpeg):
    if not ffmpeg:
        return ""
    candidate = Path(ffmpeg).with_name("ffprobe.exe" if Path(ffmpeg).suffix.lower() == ".exe" else "ffprobe")
    return str(candidate) if candidate.is_file() else ""


def parse_names(output):
    names = set()
    for line in output.splitlines():
        match = re.match(r"^\s*[A-Z.]{1,6}\s+([\w,\-]+)\s", line)
        if match:
            names.update(match.group(1).split(","))
    return names


@dataclass
class Capabilities:
    ffmpeg: str
    ffprobe: str
    version: str
    probe_version: str
    encoders: set[str]
    decoders: set[str]
    muxers: set[str]
    filters: set[str]

    def require(self, fmt, animated=False, alpha_webm=False, codec="vp9"):
        encoder = "libwebp_anim" if fmt == "webp" and animated else ENCODERS[fmt]
        needed = {"palettegen", "paletteuse"} if fmt == "gif" else set()
        if encoder not in self.encoders or MUXERS[fmt] not in self.muxers or not needed <= self.filters:
            raise FlowError(f"此 FFmpeg 构建缺少 {fmt} 所需的编码器、输出容器或调色板滤镜。请在设置中检测或更换构建。")
        decoder = "libvpx-vp9" if codec == "vp9" else "libvpx"
        if alpha_webm and decoder not in self.decoders:
            raise FlowError(f"透明 WebM 需要 {decoder} 解码器；当前构建无法可靠保留透明背景。")
        return encoder

    def report(self):
        result = [self.version, self.probe_version, f"FFmpeg：{self.ffmpeg}", f"FFprobe：{self.ffprobe}", ""]
        for fmt in ENCODERS:
            for animated in ([False, True] if fmt == "webp" else [False]):
                label = ("动态 " if animated else "") + fmt.upper()
                try:
                    self.require(fmt, animated)
                    result.append(f"✓ {label} 输出可用")
                except FlowError:
                    result.append(f"✗ {label} 输出不可用")
        result += ["", "图片解码器：" + ", ".join(sorted(self.decoders & {"png", "apng", "mjpeg", "webp", "gif", "bmp", "tiff", "vp9", "libvpx-vp9", "libvpx"})),
                   "VP9 Alpha：" + ("可用（libvpx-vp9）" if "libvpx-vp9" in self.decoders else "缺少 libvpx-vp9"),
                   "动画 WebP 导入使用 Pillow 合成帧，避免依赖 FFmpeg 构建的动画 WebP 解码能力。"]
        return "\n".join(result)


def inspect(ffmpeg, ffprobe=""):
    ffmpeg = resolve_executable(ffmpeg, "FFmpeg")
    ffprobe = resolve_executable(ffprobe or sibling_probe(ffmpeg), "FFprobe")
    version = capture([ffmpeg, "-version"]).splitlines()[0]
    probe_version = capture([ffprobe, "-version"]).splitlines()[0]
    if not version.startswith("ffmpeg version") or not probe_version.startswith("ffprobe version"):
        raise FlowError("所选程序不是有效的 FFmpeg / FFprobe。")
    sets = [parse_names(capture([ffmpeg, "-hide_banner", flag]))
            for flag in ("-encoders", "-decoders", "-muxers", "-filters")]
    return Capabilities(ffmpeg, ffprobe, version, probe_version, *sets)
