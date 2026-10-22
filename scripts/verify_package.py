"""Run the built EXE with no Python/FFmpeg on PATH, in a separate working directory."""
from pathlib import Path
import json
import os
import subprocess
import sys
import time

root = Path(__file__).resolve().parent.parent
executable = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root / "dist" / "ImageFlow" / "ImageFlow.exe"
subprocess.run([sys.executable, str(root / 'scripts' / 'check_binary_dependencies.py'), str(executable.parent)], check=True)
env = os.environ.copy()
for name in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"):
    env.pop(name, None)
env["PATH"] = str(Path(env.get("WINDIR", "C:/Windows")) / "System32")
reports = {}
for platform in ("offscreen", "windows"):
    directory = root / "artifacts" / f"packaged-{platform}"
    directory.mkdir(parents=True, exist_ok=True)
    # A failed run must never be mistaken for an earlier successful report.
    (directory / "smoke-result.json").unlink(missing_ok=True)
    env["QT_QPA_PLATFORM"] = platform
    started = time.monotonic()
    result = subprocess.run([str(executable), "--smoke-test", str(directory)], cwd=directory,
                            env=env, capture_output=True, timeout=60,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    report_file = directory / "smoke-result.json"
    report = json.loads(report_file.read_text("utf-8")) if report_file.exists() else {}
    report["exit_code"] = result.returncode
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    report["minimal_path"] = env["PATH"]
    reports[platform] = report
    print(json.dumps({platform: report}, ensure_ascii=False))
    if result.returncode or not report.get("gui") or "error" in report:
        raise SystemExit(f"Packaged {platform} verification failed: {result.stderr!r}")
(root / "artifacts" / "package-verification.json").write_text(json.dumps(reports, ensure_ascii=False, indent=2), "utf-8")
