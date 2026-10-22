"""No shell invocation. Drain both streams, bound memory, and kill process trees."""
from collections import deque
import os
import queue
import signal
import subprocess
import tempfile
import threading
import time

from .models import Cancelled, FlowError


def process_kwargs():
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def terminate_tree(proc):
    if proc.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def capture(args, timeout=20):
    try:
        result = subprocess.run([str(a) for a in args], capture_output=True, timeout=timeout,
                                encoding="utf-8", errors="replace", **process_kwargs())
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FlowError(f"无法运行程序，请检查路径和文件权限：{exc}") from exc
    if result.returncode:
        raise FlowError(f"程序执行失败（{result.returncode}）：\n{result.stderr[-6000:]}")
    return result.stdout


def stream_frames(args, frame_bytes, cancel, on_frame, timeout=60):
    """Read bounded raw frames, with responsive cancellation even during a stalled read."""
    if cancel.is_set():
        raise Cancelled("预览已取消。")
    frames = queue.Queue(maxsize=3)
    stopped = threading.Event()
    with tempfile.TemporaryFile() as errors:
        proc = subprocess.Popen([str(a) for a in args], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=errors, **process_kwargs())

        def put(value):
            while not stopped.is_set():
                try:
                    frames.put(value, timeout=.05)
                    return
                except queue.Full:
                    pass

        def read():
            try:
                while not stopped.is_set():
                    frame = proc.stdout.read(frame_bytes)
                    if not frame:
                        break
                    put(frame)
            finally:
                put(None)

        reader = threading.Thread(target=read, daemon=True)
        reader.start()
        start = time.monotonic()
        try:
            while True:
                if cancel.is_set():
                    raise Cancelled("预览已取消。")
                if time.monotonic() - start > timeout:
                    raise FlowError("预览解码超时。")
                try:
                    frame = frames.get(timeout=.05)
                except queue.Empty:
                    continue
                if frame is None:
                    break
                if len(frame) != frame_bytes:
                    raise FlowError("预览解码返回不完整帧。")
                on_frame(frame)
            proc.wait(timeout=5)
            if proc.returncode:
                errors.seek(max(0, errors.seek(0, 2) - 6000))
                raise FlowError("预览解码失败：" + errors.read().decode("utf-8", "replace"))
        finally:
            stopped.set()
            terminate_tree(proc)
            reader.join(timeout=2)
            proc.stdout.close()


def run(args, cancel, on_progress=lambda _: None, duration=None, timeout=1800, cwd=None):
    if cancel.is_set():
        raise Cancelled("任务已取消。")
    lines = queue.Queue()
    with tempfile.TemporaryFile() as errors:
        try:
            proc = subprocess.Popen([str(a) for a in args], stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=errors, cwd=cwd,
                                    **process_kwargs())
        except OSError as exc:
            raise FlowError(f"无法启动 FFmpeg：{exc}") from exc

        def read_stdout():
            for line in iter(proc.stdout.readline, b""):
                lines.put(line.decode("utf-8", errors="replace").strip())

        reader = threading.Thread(target=read_stdout, daemon=True)
        reader.start()
        started = time.monotonic()
        try:
            while proc.poll() is None or not lines.empty():
                if cancel.is_set():
                    raise Cancelled("任务已取消。")
                if time.monotonic() - started > timeout:
                    raise FlowError("处理超过 30 分钟，已停止；请降低尺寸或拆分任务。")
                try:
                    line = lines.get(timeout=0.05)
                    if line.startswith("out_time_us=") and duration:
                        try:
                            on_progress(min(99, max(0, int(float(line.split("=", 1)[1]) / 1e6 / duration * 100))))
                        except ValueError:
                            pass
                except queue.Empty:
                    pass
            if cancel.is_set():
                raise Cancelled("任务已取消。")
            errors.seek(0)
            # Keep the last 2 MB in memory; normal FFmpeg warning logs are much smaller.
            errors.seek(max(0, errors.seek(0, 2) - 2_000_000))
            log = errors.read().decode("utf-8", errors="replace")
            if proc.returncode:
                raise FlowError(f"FFmpeg 转换失败（退出码 {proc.returncode}）。请查看日志；可能是不支持的编码器、损坏文件或参数组合。\n{log}")
            return log
        finally:
            terminate_tree(proc)
            reader.join(timeout=2)
            proc.stdout.close()
