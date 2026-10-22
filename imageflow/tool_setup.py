"""Optional, explicit engine setup. Media processing never uses the network."""
from pathlib import Path, PurePosixPath
import hashlib
import os
import re
import tempfile
import urllib.request
import zipfile

from .capabilities import inspect, find_tools, sibling_probe
from .models import FlowError, Cancelled

DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
MAX_DOWNLOAD = 512 * 1024 * 1024


def candidates(app_dir, config_dir, current=""):
    """Bounded known-location search, never recursively scan user drives."""
    values = [Path(current)] if current else []
    path_ffmpeg, _ = find_tools()
    if path_ffmpeg:
        values.append(Path(path_ffmpeg))
    tools_dir = Path(config_dir) / "tools"
    values.extend(sorted(tools_dir.glob("ffmpeg-*/bin/ffmpeg.exe"), key=lambda p: p.stat().st_mtime, reverse=True))
    app_dir = Path(app_dir)
    roots = [app_dir, app_dir.parent, Path.home(), Path.home() / "Downloads"]
    for letter in "CDE":
        drive = Path(f"{letter}:/")
        roots.append(drive)
        # Common locally unpacked tools, one level only (e.g. D:/贴纸/tools/ffmpeg).
        try:
            roots.extend(p for p in list(drive.iterdir())[:200] if p.is_dir() and not p.is_symlink())
        except OSError:
            pass
    for root in roots:
        for suffix in ("ffmpeg.exe", "ffmpeg/bin/ffmpeg.exe", "tools/ffmpeg/bin/ffmpeg.exe", "Tools/ffmpeg/bin/ffmpeg.exe", "bin/ffmpeg.exe"):
            values.append(root / suffix)
    seen = set()
    for value in values:
        key = os.path.normcase(str(value.resolve()))
        if key not in seen and value.is_file():
            seen.add(key)
            yield value


def check_cancel(cancel):
    if cancel.is_set():
        raise Cancelled("已取消 FFmpeg 配置。")


def open_https(url, headers=None):
    response = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ImageFlow/1.1", **(headers or {})}), timeout=20)
    if not response.geturl().startswith("https://"):
        response.close()
        raise FlowError("下载地址未使用 HTTPS。")
    return response


def download_archive(target, cancel, status, opener):
    """Resume interrupted responses; verify every range before appending bytes."""
    digest = hashlib.sha256()
    count, total, failures, last_percent = 0, 0, 0, -1
    with target.open("wb") as output:
        while True:
            check_cancel(cancel)
            before = count
            try:
                with opener(DOWNLOAD_URL, headers={"Range": f"bytes={count}-"} if count else None) as response:
                    if count:
                        span = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", ""))
                        if (getattr(response, "status", 200) != 206 or not span or int(span[1]) != count
                                or int(span[3]) != total or int(span[2]) < count):
                            raise FlowError("下载源不支持可靠续传，请重试或手动配置 FFmpeg。")
                    else:
                        total = int(response.headers.get("Content-Length", 0))
                    if total > MAX_DOWNLOAD:
                        raise FlowError("下载文件超过允许的大小。")
                    while True:
                        check_cancel(cancel)
                        chunk = response.read(256 * 1024)
                        if not chunk:
                            break
                        count += len(chunk)
                        if count > MAX_DOWNLOAD or (total and count > total):
                            raise FlowError("下载文件超过允许的大小。")
                        digest.update(chunk)
                        output.write(chunk)
                        percent = int(count * 100 / total) if total else int(count / 1024**2)
                        if percent != last_percent:
                            status(f"正在下载 FFmpeg：{percent}%" if total else f"正在下载 FFmpeg：{percent} MB")
                            last_percent = percent
                if not total or count == total:
                    return digest.hexdigest()
            except OSError as exc:
                last_error = str(exc)
            else:
                last_error = "连接提前结束"
            failures = failures + 1 if count == before else 0
            if failures >= 3:
                raise FlowError(f"下载连接连续失败：{last_error}。请稍后重试或手动配置 FFmpeg。")
            status(f"下载连接中断，正在从 {count/1024**2:.1f} MB 继续…")


def install_download(config_dir, cancel, status, opener=open_https, inspector=inspect):
    tools_dir = Path(config_dir) / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    check_cancel(cancel)
    status("正在获取 FFmpeg 下载校验信息（gyan.dev）…")
    with opener(DOWNLOAD_URL + ".sha256") as response:
        checksum = response.read(4096).decode("ascii", errors="replace")
    match = re.search(r"\b[0-9a-fA-F]{64}\b", checksum)
    if not match:
        raise FlowError("下载源没有返回有效的 SHA-256 校验值。请稍后重试或手动选择路径。")
    expected = match.group(0).lower()
    with tempfile.TemporaryDirectory(prefix=".download-", dir=tools_dir) as temporary:
        work = Path(temporary)
        archive = work / "ffmpeg.zip"
        if download_archive(archive, cancel, status, opener) != expected:
            raise FlowError("FFmpeg 下载校验失败，已丢弃临时文件。请重新点击一键配置。")
        check_cancel(cancel)
        status("下载校验通过，正在解压并检测…")
        staging = work / "engine"
        staging.mkdir()
        selected = set()
        with zipfile.ZipFile(archive) as package:
            for entry in package.infolist():
                path = PurePosixPath(entry.filename.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts:
                    raise FlowError("下载包包含不安全路径，已停止安装。")
                name = path.name.lower()
                if name not in {"ffmpeg.exe", "ffprobe.exe", "license", "license.txt", "readme.txt"}:
                    continue
                if name in selected or entry.file_size > MAX_DOWNLOAD:
                    raise FlowError("下载包文件结构异常。")
                selected.add(name)
                target = staging / ("bin" if name.endswith(".exe") else "") / name
                target.parent.mkdir(exist_ok=True)
                with package.open(entry) as source, target.open("wb") as output:
                    copied = 0
                    while chunk := source.read(256 * 1024):
                        check_cancel(cancel)
                        copied += len(chunk)
                        if copied > MAX_DOWNLOAD:
                            raise FlowError("解压文件超过允许的大小。")
                        output.write(chunk)
        if not {"ffmpeg.exe", "ffprobe.exe"} <= selected:
            raise FlowError("下载包未包含 FFmpeg / FFprobe。")
        inspector(str(staging / "bin/ffmpeg.exe"), str(staging / "bin/ffprobe.exe"))
        check_cancel(cancel)
        destination = tools_dir / f"ffmpeg-{expected[:12]}"
        if destination.exists():
            # Preserve existing installs, even if a previous copy was damaged.
            destination = tools_dir / f"ffmpeg-{expected[:12]}-{os.urandom(3).hex()}"
        staging.rename(destination)
    return inspector(str(destination / "bin/ffmpeg.exe"), str(destination / "bin/ffprobe.exe"))


def configure_tools(app_dir, config_dir, current, cancel, status=lambda _: None):
    status("正在查找本地 FFmpeg / FFprobe…")
    for candidate in candidates(app_dir, config_dir, current):
        check_cancel(cancel)
        ffprobe = sibling_probe(str(candidate))
        if not ffprobe:
            continue
        try:
            result = inspect(str(candidate), ffprobe)
            status("已找到并验证本地 FFmpeg。")
            return result
        except FlowError:
            continue
    if os.name != "nt":
        raise FlowError("自动下载仅提供 Windows x64 构建；请手动配置本地工具。")
    return install_download(config_dir, cancel, status)
