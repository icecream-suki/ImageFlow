from dataclasses import replace
from pathlib import Path
import os
import subprocess
import tempfile
import threading

from .animation import normalize_animation, fix_webp_final_duration
from .commands import build_command, build_palette_command, output_dimensions
from .models import Cancelled, FlowError, State
from .process import run


EXTENSION = {"jpeg": ".jpg", "tiff": ".tiff"}


class OutputAllocator:
    """Reservations protect concurrent tasks. Hard-link publication prevents TOCTOU overwrites."""
    def __init__(self):
        self.lock = threading.Lock()
        self.reserved = set()
        self.inputs = set()

    @staticmethod
    def key(path):
        return os.path.normcase(str(path.resolve()))

    def protect(self, paths):
        with self.lock:
            self.inputs.update(self.key(Path(p)) for p in paths)

    def allocate(self, task):
        fmt = task.options.output_format(task.media)
        directory = task.output_dir.resolve()
        if task.options.preserve_structure and task.source_root:
            try:
                directory /= task.media.path.parent.relative_to(task.source_root.resolve())
            except ValueError:
                raise FlowError("输入文件不在导入根目录内。")
        directory.mkdir(parents=True, exist_ok=True)
        name = task.media.path.stem
        suffix = EXTENSION.get(fmt, "." + fmt)
        candidate = directory / (name + suffix)
        with self.lock:
            self.inputs.add(self.key(task.media.path))
            index = 1
            while True:
                key = self.key(candidate)
                protected = key in self.inputs
                # Detect hardlink aliases too, when both paths exist.
                if candidate.exists():
                    try:
                        protected |= any(candidate.samefile(p) for p in self.inputs if Path(p).exists())
                    except OSError:
                        pass
                if not protected and key not in self.reserved:
                    if candidate.exists() and task.options.conflict == "skip":
                        return None
                    if not candidate.exists() or task.options.conflict == "overwrite":
                        self.reserved.add(key)
                        return candidate
                candidate = directory / f"{name} ({index}){suffix}"
                index += 1

    def release(self, path):
        if path:
            with self.lock:
                self.reserved.discard(self.key(path))

    def publish(self, temporary, target, task):
        if task.options.conflict == "overwrite":
            with self.lock:
                aliases_input = target.exists() and any(target.samefile(p) for p in self.inputs if Path(p).exists())
                if aliases_input or self.key(target) in self.inputs or target.resolve() == task.media.path.resolve():
                    raise FlowError("禁止覆盖原始输入。")
                os.replace(temporary, target)
            return target
        while True:
            try:
                # Same-volume temp dir; atomic no-replace. Supported on NTFS and POSIX.
                os.link(temporary, target)
                Path(temporary).unlink()
                return target
            except FileExistsError:
                self.release(target)
                if task.options.conflict == "skip":
                    return None
                target = self.allocate(task)
            except OSError as exc:
                if os.name == "nt":
                    # Windows rename also refuses existing targets, including on exFAT.
                    try:
                        os.rename(temporary, target)
                        return target
                    except FileExistsError:
                        self.release(target)
                        if task.options.conflict == "skip":
                            return None
                        target = self.allocate(task)
                        continue
                raise FlowError(f"无法安全写入输出文件：{exc}") from exc


class Engine:
    def __init__(self, capabilities, allocator=None, log_dir=None):
        self.caps = capabilities
        self.allocator = allocator or OutputAllocator()
        self.log_dir = Path(log_dir) if log_dir else None

    def execute(self, task, update=lambda _: None):
        target = None
        try:
            if task.cancel.is_set():
                raise Cancelled("任务已取消。")
            task.options.validate(task.media)
            task.state = State.RUNNING
            update(task)
            target = self.allocator.allocate(task)
            if target is None:
                task.state = State.SKIPPED
                return
            task.output = target

            def progress(value):
                if task.progress != value:
                    task.progress = value
                    update(task)

            # Temp files are on the destination volume and are never named as final output.
            with tempfile.TemporaryDirectory(prefix=".imageflow-", dir=target.parent) as temp:
                work = Path(temp)
                input_args = None
                if task.media.animated and task.media.format != "WEBM":
                    input_args = normalize_animation(task.media, work, task.cancel, progress)
                    task.log += "Pillow 已合成动画帧（保留逐帧时间戳）；FFmpeg 负责变换与编码。\n"
                opts = task.options
                max_attempts = 7 if opts.gif_limit_kb and opts.output_format(task.media) == "gif" else 1
                result = work / ("result" + target.suffix)
                for attempt in range(max_attempts):
                    final_delay = (1 / opts.fps if opts.fps else task.media.durations[-1] if task.media.durations else
                                   1 / task.media.fps if task.media.fps else None)
                    palette = None
                    if opts.output_format(task.media) == "gif":
                        # Two passes avoid buffering the entire animation behind a split.
                        palette = work / "palette.png"
                        palette_command = build_palette_command(self.caps, task.media, opts, palette, input_args)
                        task.log += f"\n调色板分析 {attempt+1}\n{subprocess.list2cmdline(palette_command)}\n"
                        task.log += run(palette_command, task.cancel, lambda p: progress(20 + int(p * .3)),
                                        task.media.duration, cwd=work)
                        if not palette.is_file():
                            raise FlowError("FFmpeg 未能生成 GIF 优化调色板。")
                    command = build_command(self.caps, task.media, opts, result, input_args, final_delay, palette)
                    task.log += f"\n尝试 {attempt+1}\n{subprocess.list2cmdline(command)}\n"
                    task.log += run(command, task.cancel,
                                    lambda p: progress(50 + int(p * .49) if palette else 20 + int(p * .79)),
                                    task.media.duration, cwd=work)
                    if not result.exists() or result.stat().st_size == 0:
                        raise FlowError("FFmpeg 未生成有效输出。")
                    if opts.output_format(task.media) == "webp" and task.media.animated and task.media.duration:
                        patched = fix_webp_final_duration(result, task.media.duration)
                        task.log += ("已校正 WebP 最后一帧时长，保持输入总时长。\n" if patched else
                                     "所有输出帧相同，WebP 编码器合并为静态图片。\n")
                    if max_attempts == 1 or result.stat().st_size <= opts.gif_limit_kb * 1024:
                        break
                    w, h = output_dimensions(task.media, opts)
                    opts = replace(opts, resize="fit", width=max(16, round(w * .82)), height=max(16, round(h * .82)),
                                   colors=max(32, int(opts.colors * .8)),
                                   fps=max(6, (opts.fps or task.media.fps or 20) * .85))
                    task.log += f"超过体积限制，下次尝试尺寸 {opts.width}×{opts.height}、{opts.fps:.2f} fps、{opts.colors} 色。\n"
                else:
                    raise FlowError("在 7 次有限优化内未达到 GIF 体积限制。未发布超限文件；请提高限制或缩小尺寸。")
                if task.cancel.is_set():
                    raise Cancelled("任务已取消。")
                published = self.allocator.publish(result, target, task)
                self.allocator.release(target)
                target = published
                task.output = published
                task.output_size = published.stat().st_size if published else 0
                task.state = State.DONE if published else State.SKIPPED
                task.progress = 100
        except Cancelled as exc:
            task.state = State.CANCELLED
            task.error = str(exc)
        except Exception as exc:
            task.state = State.FAILED
            task.error = str(exc)
            task.log += "\n" + str(exc)
        finally:
            self.allocator.release(target)
            if self.log_dir:
                try:
                    self.log_dir.mkdir(parents=True, exist_ok=True)
                    (self.log_dir / f"{task.id}.log").write_text(task.log + "\n" + task.error, "utf-8")
                except OSError as exc:
                    task.log += f"\n无法保存日志：{exc}"
            update(task)
