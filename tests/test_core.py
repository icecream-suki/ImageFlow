from dataclasses import replace
from pathlib import Path
import json
import threading
import time
import sys
import subprocess

import pytest

from imageflow.capabilities import resolve_executable, sibling_probe, parse_names
from imageflow.commands import output_dimensions
from imageflow.config import ConfigStore, Settings
from imageflow.engine import Engine, OutputAllocator
from imageflow.models import Options, MediaInfo, Task, State, FlowError, Cancelled
from imageflow.probe import scan_inputs, probe
from imageflow.process import run


def test_invalid_paths(tmp_path):
    with pytest.raises(FlowError, match="路径不存在"):
        resolve_executable(str(tmp_path / "不存在.exe"), "FFmpeg")
    with pytest.raises(FlowError, match="选择"):
        resolve_executable("", "FFmpeg")


def test_capability_parse():
    assert parse_names(" V....D png PNG\n ..C palettegen V->V\n E image2 Image sequence\n DE matroska,webm WebM") == {"png", "palettegen", "image2", "matroska", "webm"}


def test_config_persistence_and_corruption(tmp_path):
    store = ConfigStore(tmp_path)
    settings = Settings(ffmpeg="D:/中文 空格/ffmpeg.exe", theme="深色", concurrency=3)
    store.save(settings)
    assert store.load() == settings
    store.path.write_text("broken", "utf-8")
    assert store.load() == Settings()
    assert store.notice
    assert store.path.read_text() == "broken"
    store.path.write_text('{"concurrency": 999, "theme": 123}', "utf-8")
    assert store.load().concurrency == 4
    assert store.load().theme == "跟随系统"


def test_config_readonly_fallback(tmp_path, monkeypatch):
    original = ConfigStore._check_writable
    def deny_preferred(directory):
        if directory.name == "portable_config":
            raise PermissionError("read only")
        original(directory)
    monkeypatch.setattr(ConfigStore, "_check_writable", staticmethod(deny_preferred))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    store = ConfigStore(tmp_path)
    assert store.directory == tmp_path / "local" / "ImageFlow"
    assert "不可写" in store.notice
    store.save(Settings())
    assert store.load() == Settings()


def test_geometry_and_validation(tmp_path):
    media = MediaInfo(tmp_path / "x", "PNG", 1000, 500)
    assert output_dimensions(media, Options(resize="fit", width=300, height=300)) == (300, 150)
    assert output_dimensions(media, Options(resize="fit", width=2000, height=2000)) == (1000, 500)
    assert output_dimensions(media, Options(resize="percent", percent=50)) == (500, 250)
    for opts in [Options(width=0), Options(crop=(1, 1, 1000, 500)), Options(background="white;evil"), Options(fps=0), Options(rotation=float("nan"))]:
        with pytest.raises(FlowError):
            opts.validate(media)
    with pytest.raises(FlowError, match="首帧"):
        Options().validate(replace(media, animated=True))


def test_filename_collision_and_input_protection(samples, tmp_path):
    source = samples["png"]
    media = MediaInfo(source, "PNG", 64, 48)
    allocator = OutputAllocator()
    task = Task(media, Options(conflict="overwrite"), source.parent)
    allocated = allocator.allocate(task)
    assert allocated != source
    assert "(1)" in allocated.name
    allocator.release(allocated)
    destination = tmp_path / source.name
    destination.write_bytes(b"existing")
    assert OutputAllocator().allocate(Task(media, Options(conflict="skip"), tmp_path)) is None
    assert "(1)" in OutputAllocator().allocate(Task(media, Options(), tmp_path)).name
    # An input with a different extension must be protected across the entire batch.
    allocator.protect([destination])
    protected = allocator.allocate(Task(media, Options(conflict="overwrite"), tmp_path))
    assert protected != destination


def test_atomic_publication_race(samples, tmp_path):
    allocator = OutputAllocator()
    task = Task(MediaInfo(samples["png"], "PNG", 64, 48), Options(), tmp_path)
    target = allocator.allocate(task)
    target.write_bytes(b"other writer")
    temporary = tmp_path / "temp"
    temporary.write_bytes(b"new data")
    result = allocator.publish(temporary, target, task)
    assert target.read_bytes() == b"other writer"
    assert result != target and result.read_bytes() == b"new data"


def test_scanning_and_tgs(samples, tmp_path):
    nested = samples["folder"] / "nested"
    nested.mkdir()
    (nested / "a.webp").write_bytes(b"fake")
    shallow = scan_inputs([samples["folder"]], extensions={".webp"})
    deep = scan_inputs([samples["folder"], samples["webp"]], True, {".webp"})
    assert len(shallow) == 2 and len(deep) == 3
    tgs = tmp_path / "file.tgs"
    tgs.write_bytes(b"gzip")
    with pytest.raises(FlowError, match="Lottie"):
        probe(tgs, "unused")


def test_process_failure():
    with pytest.raises(FlowError, match="退出码 7"):
        run([sys.executable, "-c", "import sys; print('test failure',file=sys.stderr); sys.exit(7)"], threading.Event())


def test_cancel_running_process_tree(tmp_path):
    pidfile = tmp_path / "pid.txt"
    cancel = threading.Event()
    code = "import os,time,pathlib; pathlib.Path(" + repr(str(pidfile)) + ").write_text(str(os.getpid())); time.sleep(60)"
    timer = threading.Timer(.5, cancel.set)
    timer.start()
    started = time.monotonic()
    with pytest.raises(Cancelled):
        run([sys.executable, "-c", code], cancel)
    timer.join()
    assert time.monotonic()-started < 8
    if sys.platform == "win32" and pidfile.exists():
        result = subprocess.run(["tasklist", "/FI", f"PID eq {pidfile.read_text()}", "/NH"], capture_output=True)
        assert b"python.exe" not in result.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process-tree verification")
def test_cancel_child_process(tmp_path):
    pidfile = tmp_path / "child.txt"
    code = ("import subprocess,sys,pathlib,time; "
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
            f"pathlib.Path({str(pidfile)!r}).write_text(str(child.pid)); time.sleep(60)")
    cancel = threading.Event()
    def wait_for_child():
        for _ in range(100):
            if pidfile.exists():
                cancel.set()
                return
            time.sleep(.05)
        cancel.set()
    thread = threading.Thread(target=wait_for_child)
    thread.start()
    try:
        with pytest.raises(Cancelled):
            run([sys.executable, "-c", code], cancel)
    finally:
        thread.join()
    assert pidfile.exists()
    result = subprocess.run(["tasklist", "/FI", f"PID eq {pidfile.read_text()}", "/NH"], capture_output=True)
    assert b"python.exe" not in result.stdout
