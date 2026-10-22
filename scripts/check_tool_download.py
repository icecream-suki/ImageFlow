"""Explicit live download verification; never part of the ordinary offline test suite."""
from pathlib import Path
import json
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from imageflow.tool_setup import install_download

root = Path(__file__).resolve().parent.parent / "artifacts" / "download-check"
root.mkdir(parents=True, exist_ok=True)
started = time.monotonic()
try:
    caps = install_download(root, threading.Event(), lambda text: print(text, flush=True))
    result = {"success": True, "version": caps.version, "ffmpeg": caps.ffmpeg, "ffprobe": caps.ffprobe,
              "elapsed_seconds": round(time.monotonic() - started, 3)}
except Exception as exc:
    result = {"success": False, "error": str(exc), "elapsed_seconds": round(time.monotonic() - started, 3)}
(root.parent / "tool-download-check.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
print(json.dumps(result, ensure_ascii=False), flush=True)
sys.exit(0 if result["success"] else 1)
