from collections import Counter
from dataclasses import replace
from pathlib import Path
import threading

from PySide6.QtCore import Qt, QObject, Signal, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QCloseEvent, QPalette, QColor
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QListWidget, QStackedWidget, QSplitter, QPushButton, QLineEdit, QFileDialog,
                               QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox,
                               QDialog, QPlainTextEdit, QProgressBar, QScrollArea)

from ..capabilities import inspect
from ..config import ConfigStore, app_directory
from ..engine import Engine
from ..models import Task, State, FlowError
from ..probe import probe, scan_inputs
from ..routing import resolve_output
from ..tool_setup import configure_tools
from ..queue import TaskQueue
from .options import OptionsPanel, combo, check, note
from .preview import PreviewWidget, PreviewCache, load_preview
from .settings import SettingsPage
from .worker import Worker


class Bridge(QObject):
    taskChanged = Signal(object)


def size_text(size):
    return f"{size/1024/1024:.2f} MB" if size >= 1024**2 else f"{size/1024:.1f} KB"


class MainWindow(QMainWindow):
    def __init__(self, store=None):
        super().__init__()
        self.store = store or ConfigStore()
        self.settings = self.store.load()
        self.caps = None
        self.queue = None
        self.imports = []
        self.workers = set()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.preview_pool = QThreadPool(self)
        self.preview_pool.setMaxThreadCount(1)
        self.preview_cache = PreviewCache()
        self.tool_cancel = threading.Event()
        self.tool_serial = 0
        self.pending_tool_paths = None
        self._system_scheme = QApplication.styleHints().colorScheme()
        QApplication.styleHints().colorSchemeChanged.connect(self.system_theme_changed)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(400)
        self.save_timer.timeout.connect(self.save_settings)
        self.preview_cancel = threading.Event()
        self.import_cancel = threading.Event()
        self.preview_serial = 0
        self.closing = False
        self.batch_started = False
        self.bridge = Bridge(self)
        self.bridge.taskChanged.connect(self.task_changed)
        self.setWindowTitle("ImageFlow · 本地图片工作台")
        self.resize(1260, 880)
        self.setMinimumSize(1000, 720)
        self.setAcceptDrops(True)
        self.make_ui()
        self.connect_autosave()
        self.apply_theme()
        self.idle_timer = QTimer(self)
        self.idle_timer.timeout.connect(self.check_idle)
        self.idle_timer.start(200)
        if self.settings.ffmpeg:
            QTimer.singleShot(0, lambda: self.test_tools(self.settings.ffmpeg, self.settings.ffprobe))
        else:
            self.statusBar().showMessage("请先在设置中选择 FFmpeg 与 FFprobe。所有图片均在本地处理。")
            self.nav.setCurrentRow(5)

    def background(self, function, result, error=None, *, partial=None, progress=None, pool=None, with_signals=False):
        worker = Worker(function, with_signals=with_signals)
        self.workers.add(worker)
        worker.signals.result.connect(result)
        worker.signals.error.connect(error or self.show_error)
        worker.signals.finished.connect(lambda: self.workers.discard(worker))
        if partial:
            worker.signals.partial.connect(partial)
        if progress:
            worker.signals.progress.connect(progress)
        (pool or self.pool).start(worker)

    def show_error(self, message):
        if not self.closing:
            QMessageBox.warning(self, "ImageFlow", message[:6000])

    def make_ui(self):
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(12, 12, 12, 12)
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(182)
        sidebar = QVBoxLayout(side)
        brand = QLabel("ImageFlow")
        brand.setObjectName("brand")
        sidebar.addWidget(brand)
        sidebar.addWidget(note("本地图片工作台"))
        self.nav = QListWidget()
        self.nav.addItems(["图片格式转换", "尺寸与裁剪", "压缩与优化", "动态图片处理", "批量任务队列", "设置"])
        self.nav.currentRowChanged.connect(self.navigate)
        sidebar.addWidget(self.nav, 1)
        sidebar.addWidget(note("本地处理 · 原图保护\nv1.1.0"))
        layout.addWidget(side)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self.make_workspace()
        self.make_queue()
        self.settings_page = SettingsPage(self.settings, self.store)
        self.settings_page.testRequested.connect(self.test_tools)
        self.settings_page.autoSetupRequested.connect(self.setup_tools)
        self.settings_page.cancelSetupRequested.connect(lambda: self.tool_cancel.set())
        self.stack.addWidget(self.settings_page)
        self.setCentralWidget(root)
        self.nav.setCurrentRow(0)

    def make_workspace(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.heading = QLabel("图片格式转换")
        self.heading.setObjectName("heading")
        layout.addWidget(self.heading)
        toolbar = QHBoxLayout()
        files = QPushButton("＋ 添加图片")
        files.clicked.connect(self.choose_files)
        folder = QPushButton("添加文件夹")
        folder.clicked.connect(self.choose_folder)
        self.recursive = check("递归子文件夹", self.settings.recursive)
        for widget in (files, folder, self.recursive):
            toolbar.addWidget(widget)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        split = QSplitter(Qt.Orientation.Horizontal)
        self.options = OptionsPanel(self.settings)
        self.options.cropEdited.connect(self.set_crop)
        self.options.ratioChanged.connect(self.set_ratio)
        self.options.setMinimumWidth(360)
        split.addWidget(self.options)
        preview_container = QWidget()
        pv = QVBoxLayout(preview_container)
        self.preview = PreviewWidget()
        self.preview.canvas.cropChanged.connect(self.options.set_crop)
        pv.addWidget(self.preview, 1)
        self.info = note("选择下方文件查看尺寸、时长和透明度。")
        pv.addWidget(self.info)
        split.addWidget(preview_container)
        split.setSizes([410, 590])
        layout.addWidget(split, 1)
        self.file_table = QTableWidget(0, 5)
        self.file_table.setHorizontalHeaderLabels(["文件名", "类型", "尺寸", "原始大小", "处理规则 / 输出"])
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.file_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.file_table.setWordWrap(False)
        self.file_table.verticalHeader().setDefaultSectionSize(32)
        self.file_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.file_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.file_table.setMinimumHeight(130)
        self.file_table.setMaximumHeight(170)
        self.file_table.itemSelectionChanged.connect(self.selection_changed)
        layout.addWidget(self.file_table)
        actions = QHBoxLayout()
        remove = QPushButton("移除选中")
        remove.clicked.connect(self.remove_selected)
        clear = QPushButton("清空导入列表")
        clear.clicked.connect(self.clear_imports)
        self.import_status = QLabel("0 个文件 · 可拖放文件或文件夹")
        actions.addWidget(remove)
        actions.addWidget(clear)
        actions.addWidget(self.import_status, 1)
        layout.addLayout(actions)
        output = QHBoxLayout()
        output.addWidget(QLabel("输出目录"))
        self.output = QLineEdit(self.settings.output_dir)
        self.output.setPlaceholderText("选择输出目录")
        output.addWidget(self.output, 1)
        browse = QPushButton("浏览…")
        browse.clicked.connect(self.choose_output)
        output.addWidget(browse)
        layout.addLayout(output)
        row = QHBoxLayout()
        self.conflict = combo([("重名自动改名", "rename"), ("重名跳过", "skip"), ("覆盖已有输出（保护输入）", "overwrite")])
        self.conflict.setCurrentIndex(max(0, self.conflict.findData(self.settings.conflict)))
        self.structure = check("保留目录结构", self.settings.preserve_structure)
        enqueue = QPushButton("全部加入队列")
        enqueue.setObjectName("primary")
        enqueue.clicked.connect(self.enqueue)
        row.addWidget(self.conflict)
        row.addWidget(self.structure)
        row.addStretch()
        row.addWidget(enqueue)
        layout.addLayout(row)
        self.stack.addWidget(page)

    def make_queue(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        title = QLabel("批量任务队列")
        title.setObjectName("heading")
        layout.addWidget(title)
        layout.addWidget(note("每个任务保存加入时的参数。失败后可查看日志并重试；需要修改参数时，请返回工作台重新加入。"))
        row = QHBoxLayout()
        for label, callback in [("▶ 开始处理", self.start_queue), ("停止全部", self.stop_queue),
                                ("取消等待", self.cancel_waiting), ("重试失败", self.retry_failed),
                                ("查看日志", self.show_log), ("打开输出目录", self.open_output)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            if label.startswith("▶"):
                button.setObjectName("primary")
            row.addWidget(button)
        layout.addLayout(row)
        self.task_table = QTableWidget(0, 7)
        self.task_table.setHorizontalHeaderLabels(["文件 / 输出", "状态", "进度", "原始", "输出", "节省比例", "错误摘要"])
        self.task_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.task_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.task_table.setWordWrap(False)
        self.task_table.verticalHeader().setDefaultSectionSize(34)
        self.task_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.task_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.task_table.cellDoubleClicked.connect(self.show_log)
        layout.addWidget(self.task_table, 1)
        self.counts = QLabel("尚无任务")
        layout.addWidget(self.counts)
        comparison = QHBoxLayout()
        original = QPushButton("预览选中任务原图")
        processed = QPushButton("预览选中任务输出")
        original.clicked.connect(lambda: self.preview_task(False))
        processed.clicked.connect(lambda: self.preview_task(True))
        comparison.addWidget(original)
        comparison.addWidget(processed)
        comparison.addStretch()
        layout.addLayout(comparison)
        self.stack.addWidget(page)

    def navigate(self, index):
        if not hasattr(self, "options"):
            return
        self.stack.setCurrentIndex(0 if index < 4 else index - 3)
        if index < 4:
            self.options.pages.setCurrentIndex(index)
            self.heading.setText(self.nav.item(index).text())
            self.preview.canvas.cropping = index == 1 and self.options.crop_enabled.isChecked()
        else:
            self.preview.timer.stop()

    def test_tools(self, ffmpeg, ffprobe):
        if self.queue and self.queue.active:
            self.pending_tool_paths = (ffmpeg, ffprobe)
            self.settings_page.report.setPlainText("路径已保存，将在当前任务结束后检测并切换。")
            return
        self.run_tool_setup(lambda _, cancel: inspect(ffmpeg, ffprobe), "正在后台检测 FFmpeg / FFprobe 与图片处理能力…")

    def setup_tools(self):
        if self.queue and self.queue.active:
            self.settings_page.report.setPlainText("请在当前转换结束后使用一键配置；处理中的任务继续使用原工具。")
            return
        current = self.settings_page.ffmpeg.text().strip()
        self.run_tool_setup(lambda signals, cancel: configure_tools(app_directory(), self.store.directory, current,
                                                                   cancel, signals.progress.emit),
                            "正在查找本地工具…")

    def run_tool_setup(self, function, message):
        self.tool_cancel.set()
        self.tool_cancel = threading.Event()
        cancel = self.tool_cancel
        self.tool_serial += 1
        serial = self.tool_serial
        self.settings_page.set_busy(True)
        self.settings_page.report.setPlainText(message)
        self.caps = None

        def success(caps):
            if serial != self.tool_serial or self.closing:
                return
            if cancel.is_set():
                failure("已取消配置。可重新检测或一键配置。")
                return
            self.caps = caps
            self.settings_page.ffmpeg.setText(caps.ffmpeg)
            self.settings_page.ffprobe.setText(caps.ffprobe)
            self.settings_page.report.setPlainText(caps.report())
            self.settings_page.set_busy(False)
            self.save_settings()
            if self.queue:
                self.queue.engine.caps = caps
            self.statusBar().showMessage("FFmpeg 已就绪，可以导入图片。")

        def failure(message):
            if serial != self.tool_serial or self.closing:
                return
            self.settings_page.set_busy(False)
            self.settings_page.report.setPlainText(message)
            self.statusBar().showMessage("FFmpeg 尚未就绪，请重试或手动选择路径。")

        self.background(lambda signals: function(signals, cancel), success, failure, with_signals=True,
                        progress=lambda text: self.settings_page.report.setPlainText(text)
                        if serial == self.tool_serial and not self.closing else None)

    def connect_autosave(self):
        self.options.changed.connect(self.schedule_save)
        self.settings_page.changed.connect(self.schedule_save)
        self.output.textChanged.connect(self.settings_page.output.setText)
        self.settings_page.output.textChanged.connect(self.output.setText)
        self.structure.toggled.connect(self.settings_page.structure.setChecked)
        self.settings_page.structure.toggled.connect(self.structure.setChecked)
        self.recursive.toggled.connect(self.schedule_save)
        self.conflict.currentIndexChanged.connect(self.schedule_save)

    def schedule_save(self):
        if not self.closing:
            self.settings_page.saved.setText("正在自动保存…")
            self.save_timer.start()

    def save_settings(self):
        self.save_timer.stop()
        updated = self.settings_page.values(self.settings)
        updated.image_format = self.options.image_format.currentData()
        updated.animation_format = self.options.animation_format.currentData()
        updated.routing_rules = self.options.rules_editor.rules()
        updated.processing = self.options.snapshot()
        updated.compression = self.options.anim_preset.currentText()
        updated.recursive = self.recursive.isChecked()
        updated.conflict = self.conflict.currentData()
        try:
            self.store.save(updated)
        except OSError as exc:
            self.settings_page.saved.setText(f"自动保存失败：{exc}")
            self.statusBar().showMessage(f"配置保存失败：{exc}")
            return
        old = self.settings
        self.settings = updated
        if updated.theme != old.theme:
            self.apply_theme()
        if self.queue:
            self.queue.set_concurrency(updated.concurrency)
        self.refresh_imports()
        self.settings_page.saved.setText("选项已自动保存" + (" · 并发数在当前批次结束后生效" if self.queue and self.queue.concurrency != updated.concurrency else ""))

    def choose_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "导入图片", "", "图片与贴纸 (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff *.gif *.apng *.webm *.tgs)")
        if files:
            self.import_paths(files)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "导入文件夹")
        if folder:
            self.import_paths([folder])

    def choose_output(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", self.output.text())
        if path:
            self.output.setText(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and all(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.import_paths([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()

    def import_paths(self, paths):
        if not self.caps:
            self.nav.setCurrentRow(5)
            self.show_error("请先选择 FFmpeg 与 FFprobe 并完成连接检测。")
            return
        recursive = self.recursive.isChecked()
        caps = self.caps
        self.import_status.setText("正在后台扫描和识别图片…")

        def work():
            results = []
            for path, root in scan_inputs(paths, recursive):
                if self.import_cancel.is_set():
                    break
                try:
                    results.append((path, root, probe(path, caps.ffprobe), ""))
                except Exception as exc:
                    results.append((path, root, None, str(exc)))
            return results

        def loaded(results):
            existing = {item[0] for item in self.imports}
            self.imports += [item for item in results if item[0] not in existing]
            self.refresh_imports()
            self.nav.setCurrentRow(0)
            if self.file_table.rowCount() and not self.file_table.selectedItems():
                self.file_table.selectRow(0)

        self.background(work, loaded)

    def refresh_imports(self):
        self.file_table.blockSignals(True)
        self.file_table.setRowCount(len(self.imports))
        for row, (path, root, media, error) in enumerate(self.imports):
            target, rule = resolve_output(media, self.options.image_format.currentData(),
                                          self.options.animation_format.currentData(), self.options.rules_editor.rules()) if media else ("", "")
            values = [path.name, ("动态 " if media and media.animated else "") + (media.format if media else "不支持"),
                      f"{media.width} × {media.height}" if media else "—", size_text(path.stat().st_size) if path.exists() else "—",
                      f"{media.format} → {target.upper()} · {rule}" if media else error]
            for col, value in enumerate(values):
                item = self.file_table.item(row, col)
                if item is None:
                    item = QTableWidgetItem(value)
                    self.file_table.setItem(row, col, item)
                else:
                    item.setText(value)
                item.setToolTip(str(path) if col == 0 else value)
        self.file_table.blockSignals(False)
        self.import_status.setText(f"{len(self.imports)} 个文件 · {sum(item[2] is None for item in self.imports)} 个不支持 / 错误")

    def selected_rows(self, table):
        return sorted({item.row() for item in table.selectedItems()})

    def remove_selected(self):
        rows = set(self.selected_rows(self.file_table))
        self.imports = [item for i, item in enumerate(self.imports) if i not in rows]
        self.refresh_imports()
        self.preview_serial += 1
        self.preview_cancel.set()
        self.preview.clear()

    def clear_imports(self):
        self.imports.clear()
        self.refresh_imports()
        self.preview_serial += 1
        self.preview_cancel.set()
        self.preview.clear()

    def selection_changed(self):
        rows = self.selected_rows(self.file_table)
        if not rows or rows[0] >= len(self.imports):
            return
        path, root, media, error = self.imports[rows[0]]
        if not media:
            self.preview.clear()
            self.info.setText(error)
            return
        self.show_media(media, "原图预览")

    def show_media(self, media, caption):
        self.preview_serial += 1
        serial = self.preview_serial
        self.preview_cancel.set()
        cancel = threading.Event()
        self.preview_cancel = cancel
        self.preview.clear()
        alpha = "有" if media.alpha is True else "无" if media.alpha is False else "未知"
        fps = f"{media.fps:.2f} fps（平均）" if media.fps else "未知 / 静态"
        duration = f"{media.duration:.3f} 秒" if media.duration else "未知 / 静态"
        self.info.setText(f"{media.path.name} · {media.width} × {media.height} · {size_text(media.size)}\n"
                          f"透明区域：{alpha}　帧率：{fps}　时长：{duration}\n" + "\n".join(media.warnings))
        self.preview.caption.setText(caption + " · 加载中…")
        caps = self.caps
        if not caps:
            self.preview.caption.setText("请先完成工具配置。")
            return
        try:
            cache_key = self.preview_cache.key(media, caps)
        except OSError as exc:
            self.preview.caption.setText("文件已不可访问：" + str(exc))
            return

        def display(data, partial=False):
            if serial == self.preview_serial and not self.closing:
                self.preview.set_data(data)
                self.preview.caption.setText(caption + (" · 正在加载动画…" if partial else ""))
                if caption == "原图预览":
                    self.options.emit_crop()
                    self.set_ratio(self.options.ratio.currentData())

        def ready(data):
            if not cancel.is_set():
                self.preview_cache.put(cache_key, data)
                display(data)

        def error(message):
            if serial == self.preview_serial and not self.closing:
                self.preview.caption.setText("无法预览：" + message[:300])

        cached = self.preview_cache.get(cache_key)
        if cached is not None:
            display(cached)
            return
        self.background(lambda signals: load_preview(media, caps, cancel, signals.partial.emit), ready, error,
                        partial=lambda data: display(data, True), pool=self.preview_pool, with_signals=True)

    def set_crop(self, crop):
        self.preview.canvas.crop = crop
        self.preview.canvas.cropping = crop is not None and self.nav.currentRow() == 1
        self.preview.canvas.update()

    def set_ratio(self, ratio):
        self.preview.canvas.ratio = ratio

    def enqueue(self):
        if not self.caps:
            self.show_error("请先完成 FFmpeg 检测。")
            return
        if not self.output.text().strip():
            self.show_error("请先选择输出目录。")
            return
        valid = [item for item in self.imports if item[2] is not None]
        if not valid:
            self.show_error("没有可处理的图片，请先导入文件。")
            return
        opts = self.options.options()
        opts.conflict = self.conflict.currentData()
        opts.preserve_structure = self.structure.isChecked()
        try:
            for _, _, media, _ in valid:
                opts.validate(media)
                fmt = opts.output_format(media)
                self.caps.require(fmt, media.animated and fmt in {"gif", "webp", "apng"},
                                  media.format == "WEBM" and media.alpha is True and opts.preserve_alpha, media.codec)
        except FlowError as exc:
            self.show_error(str(exc))
            return
        if not self.queue:
            self.queue = TaskQueue(Engine(self.caps, log_dir=self.store.directory / "logs"), self.settings.concurrency,
                                   self.bridge.taskChanged.emit)
        self.queue.engine.allocator.protect([item[0] for item in self.imports])
        for path, root, media, error in valid:
            self.queue.add(Task(media, replace(opts), Path(self.output.text()).expanduser(), root))
        self.nav.setCurrentRow(4)

    def start_queue(self):
        if self.queue and self.caps:
            self.batch_started = True
            self.queue.start()
        elif not self.caps:
            self.show_error("FFmpeg 尚未检测成功。")

    def stop_queue(self):
        if self.queue:
            self.queue.stop()

    def cancel_waiting(self):
        if self.queue:
            self.queue.cancel_waiting()

    def retry_failed(self):
        if self.queue and self.caps:
            self.batch_started = True
            self.queue.retry_failed()

    def task_changed(self, task):
        if not self.queue:
            return
        tasks = self.queue.tasks
        self.task_table.setRowCount(len(tasks))
        row = next((i for i, t in enumerate(tasks) if t.id == task.id), -1)
        if row < 0:
            return
        saved = f"{(1-task.output_size/task.media.size)*100:.1f}%" if task.output_size else "—"
        values = [task.media.path.name + (" → " + task.output.name if task.output else ""), task.state.value, "",
                  size_text(task.media.size), size_text(task.output_size) if task.output_size else "—", saved,
                  task.error.splitlines()[0] if task.error else ""]
        for col, value in enumerate(values):
            if col == 2:
                bar = self.task_table.cellWidget(row, col)
                if bar is None:
                    bar = QProgressBar()
                    self.task_table.setCellWidget(row, col, bar)
                bar.setValue(task.progress)
            else:
                item = QTableWidgetItem(value)
                item.setToolTip(str(task.output) if col == 0 and task.output else task.error if col == 6 else value)
                self.task_table.setItem(row, col, item)
        counts = Counter(t.state.value for t in tasks)
        self.counts.setText("　 ·　".join(f"{s.value} {counts[s.value]}" for s in State))

    def current_task(self):
        rows = self.selected_rows(self.task_table)
        return self.queue.tasks[rows[0]] if self.queue and rows else None

    def show_log(self, *args):
        task = self.current_task()
        if not task:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("处理日志 · " + task.media.path.name)
        dialog.resize(850, 600)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(task.error + "\n\n" + task.log)
        layout.addWidget(text)
        dialog.exec()

    def open_output(self):
        task = self.current_task()
        path = task.output.parent if task and task.output else Path(self.output.text()) if self.output.text() else None
        if path and path.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    def preview_task(self, processed):
        task = self.current_task()
        if not task:
            return
        if processed:
            if task.state != State.DONE or not task.output:
                self.show_error("任务尚未成功完成。")
                return
            self.background(lambda: probe(task.output, self.caps.ffprobe),
                            lambda media: self.open_preview_media(media, "处理后预览"))
        else:
            self.open_preview_media(task.media, "原图预览")

    def open_preview_media(self, media, caption):
        self.nav.setCurrentRow(0)
        self.show_media(media, caption)

    def check_idle(self):
        if self.queue and not self.queue.active:
            self.queue.set_concurrency(self.settings.concurrency)
        if self.pending_tool_paths and (not self.queue or not self.queue.active) and not self.closing:
            paths, self.pending_tool_paths = self.pending_tool_paths, None
            self.test_tools(*paths)
        if self.batch_started and self.queue and not self.queue.active:
            self.batch_started = False
            if self.settings.auto_open and any(t.state == State.DONE for t in self.queue.tasks):
                self.open_output()
        if self.closing and not self.workers and (not self.queue or not self.queue.active):
            self.close()

    def closeEvent(self, event: QCloseEvent):
        if self.save_timer.isActive():
            self.save_settings()
        self.tool_cancel.set()
        self.preview.timer.stop()
        self.preview_cancel.set()
        self.import_cancel.set()
        if self.queue:
            self.queue.stop()
        if self.workers or (self.queue and self.queue.active):
            self.closing = True
            self.setEnabled(False)
            self.statusBar().showMessage("正在结束后台任务并清理临时文件…")
            event.ignore()
            return
        if self.queue:
            self.queue.shutdown()
        self.idle_timer.stop()
        event.accept()

    def system_theme_changed(self, scheme):
        self._system_scheme = scheme
        if self.settings.theme == "跟随系统":
            self.apply_theme()

    def apply_theme(self):
        dark = self.settings.theme == "深色" or (self.settings.theme == "跟随系统" and self._system_scheme == Qt.ColorScheme.Dark)
        bg, panel, text, edge, field = (("#151b27", "#202a3a", "#e8edf5", "#354157", "#182231") if dark else
                                      ("#f4f6fa", "#ffffff", "#253249", "#dbe2ed", "#ffffff"))
        palette = QPalette()
        for role, color in [(QPalette.ColorRole.Window, bg), (QPalette.ColorRole.WindowText, text),
                            (QPalette.ColorRole.Base, field), (QPalette.ColorRole.AlternateBase, panel),
                            (QPalette.ColorRole.Text, text), (QPalette.ColorRole.Button, panel),
                            (QPalette.ColorRole.ButtonText, text), (QPalette.ColorRole.Highlight, "#2879dc"),
                            (QPalette.ColorRole.HighlightedText, "#ffffff"), (QPalette.ColorRole.ToolTipBase, panel),
                            (QPalette.ColorRole.ToolTipText, text)]:
            palette.setColor(role, QColor(color))
        QApplication.instance().setPalette(palette)
        self.setPalette(palette)
        self.setStyleSheet(f"""
            QWidget {{ font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; color: {text}; }}
            QMainWindow, QDialog {{ background: {bg}; }}
            QWidget#sidebar {{ background: {panel}; border-radius: 12px; }}
            QLabel#brand {{ font-size: 23px; font-weight: 700; padding: 14px 0; color: #368bf4; }}
            QLabel#heading {{ font-size: 25px; font-weight: 600; padding: 4px 0 12px 0; }}
            QLabel#note {{ color: {'#aebbd0' if dark else '#65738a'}; line-height: 1.5; }}
            QListWidget {{ background: transparent; border: 0; outline: 0; }}
            QListWidget::item {{ padding: 14px 8px; margin: 3px 0; border-radius: 7px; }}
            QListWidget::item:selected {{ background: {'#254364' if dark else '#e5efff'}; color: {'#a4ccff' if dark else '#1766c1'}; }}
            QPushButton {{ background: {panel}; border: 1px solid {edge}; padding: 7px 11px; border-radius: 6px; }}
            QPushButton:hover {{ border-color: #3989ed; }}
            QPushButton#primary {{ background: #2879dc; border-color: #2879dc; color: white; font-weight: 600; }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{ background: {field}; border: 1px solid {edge}; border-radius: 5px; padding: 5px; min-height: 19px; }}
            QComboBox QAbstractItemView {{ background: {panel}; color: {text}; selection-background-color: #2879dc; }}
            QTableWidget, QPlainTextEdit {{ background: {panel}; border: 1px solid {edge}; gridline-color: {edge}; selection-background-color: {'#284264' if dark else '#dceaff'}; selection-color: {text}; }}
            QHeaderView::section {{ background: {bg}; padding: 7px; border: 0; border-bottom: 1px solid {edge}; }}
            QTableCornerButton::section {{ background: {bg}; border: 1px solid {edge}; }}
            QScrollArea {{ border: 0; background: transparent; }}
            QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {'#7e90aa' if dark else '#9aa9be'}; border-radius: 3px; background: {field}; }}
            QCheckBox::indicator:checked {{ background: #2879dc; border: 2px solid {'#9bcbff' if dark else '#1355a5'}; }}
            QProgressBar {{ border: 0; background: {bg}; text-align: center; border-radius: 4px; }}
            QProgressBar::chunk {{ background: #4b9be9; border-radius: 4px; }}
            QWidget:disabled {{ color: {'#66738a' if dark else '#a2abb9'}; }}
        """)
