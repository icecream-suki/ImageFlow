from dataclasses import asdict, dataclass, fields, field
from pathlib import Path
import json
import os
import sys
import tempfile


@dataclass
class Settings:
    ffmpeg: str = ""
    ffprobe: str = ""
    output_dir: str = ""
    image_format: str = "png"
    animation_format: str = "gif"
    compression: str = "平衡模式"
    concurrency: int = 2
    preserve_structure: bool = False
    auto_open: bool = False
    theme: str = "跟随系统"
    routing_rules: list[dict] = field(default_factory=list)
    processing: dict = field(default_factory=dict)
    recursive: bool = False
    conflict: str = "rename"


def app_directory():
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent


class ConfigStore:
    def __init__(self, base: Path | None = None):
        preferred = (base or app_directory()) / "portable_config"
        self.notice = ""
        try:
            self._check_writable(preferred)
            self.directory = preferred
        except OSError:
            self.directory = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".config"))) / "ImageFlow"
            self._check_writable(self.directory)
            self.notice = f"软件目录不可写，配置与日志保存在：{self.directory}"
        self.path = self.directory / "settings.json"

    @staticmethod
    def _check_writable(directory):
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=directory):
            pass

    def load(self):
        try:
            data = json.loads(self.path.read_text("utf-8"))
            defaults = Settings()
            if not isinstance(data, dict):
                raise ValueError("配置必须是 JSON 对象")
            values = {f.name: data[f.name] for f in fields(Settings)
                      if f.name in data and type(data[f.name]) is type(getattr(defaults, f.name))}
            result = Settings(**values)
            result.concurrency = max(1, min(4, result.concurrency))
            from .routing import clean_rules
            result.routing_rules = clean_rules(result.routing_rules)
            if result.image_format not in {"png", "jpeg", "webp", "bmp", "tiff"}:
                result.image_format = "png"
            if result.animation_format not in {"gif", "apng", "webp"}:
                result.animation_format = "gif"
            if result.theme not in {"浅色", "深色", "跟随系统"}:
                result.theme = "跟随系统"
            if result.conflict not in {"rename", "skip", "overwrite"}:
                result.conflict = "rename"
            return result
        except FileNotFoundError:
            return Settings()
        except (ValueError, OSError) as exc:
            self.notice = f"配置无法读取，已使用默认设置；原文件保留。{exc}"
            return Settings()

    def save(self, settings):
        fd, name = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(asdict(settings), stream, ensure_ascii=False, indent=2)
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)
