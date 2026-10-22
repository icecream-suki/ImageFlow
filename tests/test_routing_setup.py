from dataclasses import replace
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import hashlib
import threading
import zipfile

import pytest

from imageflow.config import ConfigStore
from imageflow.engine import Engine
from imageflow.models import MediaInfo, Options, Task, FlowError, Cancelled, State
from imageflow.queue import TaskQueue
from imageflow.routing import resolve_output, clean_rules
from imageflow import tool_setup


def test_rules_content_order_and_defaults(tmp_path):
    media = MediaInfo(tmp_path / "misleading.png", "WEBP", 10, 10, animated=True)
    rules = clean_rules([dict(source="webp", kind="animated", target="apng"),
                         dict(source="any", kind="any", target="jpeg")])
    assert resolve_output(media, "png", "gif", rules) == ("apng", "规则 1")
    assert resolve_output(replace(media, animated=False), "png", "gif", rules)[0] == "jpeg"
    rules[0]["enabled"] = False
    assert resolve_output(media, "png", "gif", rules)[0] == "jpeg"
    assert resolve_output(media, "png", "webp", [])[0] == "webp"
    assert resolve_output(replace(media, animated=False), "tiff", "webp", [])[0] == "tiff"
    opts = Options(auto_route=True, routing_rules=rules)
    with pytest.raises(FlowError, match="首帧"):
        opts.validate(media)


def test_corrupt_rules_and_legacy_config(tmp_path):
    assert clean_rules([{}, [], dict(source=[], kind="any", target="png")]) == []
    store = ConfigStore(tmp_path)
    store.path.write_text('{"image_format":"webp","theme":"深色","routing_rules":[{}],"processing":123}', "utf-8")
    value = store.load()
    assert value.image_format == "webp" and value.theme == "深色"
    assert value.processing == {} and value.routing_rules == []


def test_queue_snapshot_and_concurrency_change(tmp_path):
    source = tmp_path / "x.webp"
    source.write_bytes(b"placeholder")
    opts = Options(auto_route=True, routing_rules=clean_rules([dict(source="webp", kind="static", target="png")]))
    task = Task(MediaInfo(source, "WEBP", 10, 10), opts, tmp_path)
    queue = TaskQueue(Engine(None))
    try:
        queue.add(task)
        opts.routing_rules[0]["target"] = "jpeg"
        queue.set_concurrency(3)
        assert task.options.output_format(task.media) == "png"
        assert task.state == State.WAITING and not task.cancel.is_set()
        assert queue.concurrency == 3
    finally:
        queue.shutdown()


def package_bytes(extra=None):
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("ffmpeg-test/bin/ffmpeg.exe", b"engine")
        archive.writestr("ffmpeg-test/bin/ffprobe.exe", b"probe")
        archive.writestr("ffmpeg-test/LICENSE", b"license")
        if extra:
            archive.writestr(extra, b"bad")
    return output.getvalue()


def fake_download(data, digest=None):
    def open_response(url, headers=None):
        response = BytesIO((digest or hashlib.sha256(data).hexdigest()).encode() if url.endswith(".sha256") else data)
        response.headers = {"Content-Length": str(len(data))}
        return response
    return open_response


def check_extracted(ffmpeg, ffprobe):
    assert Path(ffmpeg).read_bytes() == b"engine"
    assert Path(ffprobe).read_bytes() == b"probe"
    return SimpleNamespace(ffmpeg=ffmpeg, ffprobe=ffprobe)


def test_download_verified_install_and_preservation(tmp_path):
    data = package_bytes()
    args = (tmp_path, threading.Event(), lambda _: None)
    first = tool_setup.install_download(*args, opener=fake_download(data), inspector=check_extracted)
    second = tool_setup.install_download(*args, opener=fake_download(data), inspector=check_extracted)
    assert first.ffmpeg != second.ffmpeg
    assert Path(first.ffmpeg).is_file()
    assert (Path(second.ffmpeg).parent.parent / "license").is_file()
    assert not list((tmp_path / "tools").glob(".download-*"))


@pytest.mark.parametrize("case", ["checksum", "traversal", "cancel", "invalid_executable"])
def test_download_failure_cleans_staging(tmp_path, case):
    data = package_bytes("../escape.exe" if case == "traversal" else None)
    cancel = threading.Event()
    if case == "cancel":
        cancel.set()
    def inspector(*args):
        if case == "invalid_executable":
            raise FlowError("unusable executable")
        return check_extracted(*args)
    with pytest.raises(FlowError):
        tool_setup.install_download(tmp_path, cancel, lambda _: None,
                                    opener=fake_download(data, "0"*64 if case == "checksum" else None), inspector=inspector)
    assert not list((tmp_path / "tools").iterdir())
    assert not (tmp_path / "escape.exe").exists()


def test_download_resume_validates_range(tmp_path):
    data = package_bytes()
    calls = []
    def interrupted(url, headers=None):
        calls.append(headers)
        if not headers:
            response = BytesIO(data[:100])
            response.headers = {"Content-Length": str(len(data))}
        else:
            assert headers == {"Range": "bytes=100-"}
            response = BytesIO(data[100:])
            response.status = 206
            response.headers = {"Content-Range": f"bytes 100-{len(data)-1}/{len(data)}"}
        return response
    target = tmp_path / "resume.zip"
    assert tool_setup.download_archive(target, threading.Event(), lambda _: None, interrupted) == hashlib.sha256(data).hexdigest()
    assert target.read_bytes() == data and len(calls) == 2
    def wrong_range(url, headers=None):
        response = interrupted(url, headers)
        if headers:
            response.status = 200
        return response
    with pytest.raises(FlowError, match="续传"):
        tool_setup.download_archive(target, threading.Event(), lambda _: None, wrong_range)


@pytest.mark.integration
def test_oneclick_uses_local_engine(caps, tmp_path, monkeypatch):
    monkeypatch.setattr(tool_setup, "install_download", lambda *a: pytest.fail("Local engine must avoid network"))
    result = tool_setup.configure_tools(tmp_path, tmp_path, caps.ffmpeg, threading.Event())
    assert result.ffmpeg == caps.ffmpeg and result.ffprobe == caps.ffprobe


@pytest.mark.integration
def test_custom_routing_real_batch(caps, samples, tmp_path):
    from imageflow.probe import probe
    options = Options(auto_route=True, image_format="bmp", animation_format="gif", lossless_webp=True,
                      routing_rules=clean_rules([dict(source="webp", kind="animated", target="webp")]))
    queue = TaskQueue(Engine(caps), concurrency=2)
    try:
        for name in ["png", "animated_webp", "apng"]:
            queue.add(Task(probe(samples[name], caps.ffprobe), options, tmp_path / "outputs"))
        queue.start()
        for future in list(queue.futures.values()):
            future.result(timeout=30)
        assert all(task.state == State.DONE for task in queue.tasks)
        outputs = [probe(task.output, caps.ffprobe) for task in queue.tasks]
        assert [media.format for media in outputs] == ["BMP", "WEBP", "GIF"]
        assert [media.animated for media in outputs] == [False, True, True]
    finally:
        queue.shutdown()
