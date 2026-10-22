"""Explicit packaged-executable verification mode, never used in normal startup."""
from pathlib import Path
import json
import os
import platform
import time

from PIL import Image, ImageDraw
from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase

from .capabilities import inspect
from .config import ConfigStore
from .engine import Engine
from .gui.main import MainWindow
from .models import Task, Options, State
from .probe import probe
from .gui.preview import load_preview
from .process import capture


def run_smoke(app, directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "msyh.ttc"
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    result = {"python": platform.python_version(), "platform": platform.platform(), "gui": False, "conversion": "not requested"}
    window = MainWindow(ConfigStore(directory / "smoke-profile"))
    window.show()

    def verify():
        try:
            app.processEvents()
            for index in range(6):
                window.nav.setCurrentRow(index)
                app.processEvents()
            result["gui"] = True
            window.options.rules_editor.add_rule()
            window.settings_page.theme.setCurrentText("跟随系统")
            window.save_settings()
            saved = window.store.load()
            if saved.routing_rules != window.options.rules_editor.rules() or saved.theme != "跟随系统":
                raise RuntimeError("Autosave validation failed")
            result["autosave_routing"] = True
            ffmpeg = os.environ.get("IMAGEFLOW_FFMPEG")
            if ffmpeg:
                caps = inspect(ffmpeg, os.environ.get("IMAGEFLOW_FFPROBE", ""))
                image = Image.new("RGBA", (96, 64), (0, 0, 0, 0))
                ImageDraw.Draw(image).rounded_rectangle((12, 12, 80, 52), radius=12, fill=(30, 140, 220, 255))
                source = directory / "测试 input.webp"
                image.save(source, lossless=True)
                task = Task(probe(source, caps.ffprobe), window.options.options(), directory / "output")
                Engine(caps).execute(task)
                if task.state != State.DONE:
                    raise RuntimeError(task.log)
                with Image.open(task.output) as converted:
                    if converted.convert("RGBA").getpixel((0, 0))[3] != 0:
                        raise RuntimeError("Alpha validation failed")
                result["conversion"] = "passed: WebP to PNG, Unicode path and transparent pixel"
                result["ffmpeg"] = caps.version
                webm = directory / "preview-alpha.webm"
                capture([caps.ffmpeg, "-y", "-v", "error", "-loop", "1", "-i", str(source),
                         "-t", "0.3", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", str(webm)])
                first = []
                preview = load_preview(probe(webm, caps.ffprobe), caps, on_first=lambda d: first.append(d))
                if not first or len(preview.frames) < 2 or preview.frames[0][3] != 0:
                    raise RuntimeError("Raw WebM preview validation failed")
                window.preview.set_data(preview)
                result["webm_preview"] = "passed: first frame, animation and transparent pixel"
            window.nav.setCurrentRow(0)
            app.processEvents()
            window.grab().save(str(directory / "packaged-window.png"))
            (directory / "smoke-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
            window.close()
            app.exit(0)
        except Exception as exc:
            result["error"] = str(exc)
            (directory / "smoke-result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
            window.close()
            app.exit(1)

    QTimer.singleShot(200, verify)
    return app.exec()
