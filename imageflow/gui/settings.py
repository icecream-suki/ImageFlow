from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QFileDialog, QPlainTextEdit, QScrollArea)

from ..capabilities import find_tools, sibling_probe
from ..config import Settings
from dataclasses import replace
from .options import combo, spin, check, note


class SettingsPage(QWidget):
    testRequested = Signal(str, str)
    changed = Signal()
    autoSetupRequested = Signal()
    cancelSetupRequested = Signal()

    def __init__(self, settings, store):
        super().__init__()
        outer = QVBoxLayout(self)
        title = QLabel("设置")
        title.setObjectName("heading")
        outer.addWidget(title)
        form = QFormLayout()
        self.path_buttons = []
        self.ffmpeg = QLineEdit(settings.ffmpeg)
        self.ffprobe = QLineEdit(settings.ffprobe)
        for label, widget, name in [("FFmpeg 路径", self.ffmpeg, "ffmpeg"), ("FFprobe 路径", self.ffprobe, "ffprobe")]:
            row = QHBoxLayout()
            row.addWidget(widget, 1)
            button = QPushButton("浏览…")
            button.clicked.connect(lambda _, n=name: self.browse(n))
            self.path_buttons.append(button)
            row.addWidget(button)
            form.addRow(label, row)
        self.ffmpeg.editingFinished.connect(self.autofill_probe)
        row = QHBoxLayout()
        self.auto_setup = QPushButton("一键配置 FFmpeg")
        self.auto_setup.setObjectName("primary")
        self.auto_setup.clicked.connect(self.autoSetupRequested)
        self.cancel_setup = QPushButton("取消配置")
        self.cancel_setup.setEnabled(False)
        self.cancel_setup.clicked.connect(self.cancelSetupRequested)
        find = QPushButton("自动查找 PATH")
        find.clicked.connect(self.find)
        self.path_buttons.append(find)
        self.test = QPushButton("测试连接与格式能力")
        self.test.clicked.connect(lambda: self.testRequested.emit(self.ffmpeg.text(), self.ffprobe.text()))
        row.addWidget(self.auto_setup)
        row.addWidget(self.cancel_setup)
        row.addWidget(find)
        row.addWidget(self.test)
        form.addRow(row)
        form.addRow(note("一键配置先查找本地工具；未找到时从 gyan.dev 下载并校验到便携配置目录。仅下载工具需要联网，图片始终在本地处理。"))
        self.output = QLineEdit(settings.output_dir)
        outrow = QHBoxLayout()
        outrow.addWidget(self.output)
        output_button = QPushButton("浏览…")
        output_button.clicked.connect(self.select_output)
        outrow.addWidget(output_button)
        form.addRow("默认输出目录", outrow)
        self.concurrency = spin(1, 4, settings.concurrency)
        self.structure = check("默认保留文件夹结构", settings.preserve_structure)
        self.auto_open = check("处理结束后自动打开输出目录", settings.auto_open)
        self.theme = combo([("跟随系统", "跟随系统"), ("浅色", "浅色"), ("深色", "深色")])
        self.theme.setCurrentText(settings.theme)
        form.addRow("并发任务数", self.concurrency)
        form.addRow(self.structure)
        form.addRow(self.auto_open)
        form.addRow("界面主题", self.theme)
        outer.addLayout(form)
        self.saved = note("选项更改后自动保存")
        outer.addWidget(self.saved)
        outer.addWidget(note(f"配置目录：{store.directory}\n{store.notice}\nFFmpeg 无需安装或修改 PATH；可直接选择任意文件夹中的 ffmpeg.exe。"))
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        self.report.setPlaceholderText("点击测试连接，查看版本、编码器、解码器和输出格式支持。")
        outer.addWidget(self.report, 1)
        for widget in (self.ffmpeg, self.ffprobe, self.output):
            widget.textChanged.connect(self.changed)
        self.concurrency.valueChanged.connect(self.changed)
        self.structure.toggled.connect(self.changed)
        self.auto_open.toggled.connect(self.changed)
        self.theme.currentIndexChanged.connect(self.changed)
        for widget in (self.ffmpeg, self.ffprobe):
            widget.editingFinished.connect(lambda: self.testRequested.emit(self.ffmpeg.text(), self.ffprobe.text()))

    def browse(self, name):
        path, _ = QFileDialog.getOpenFileName(self, f"选择 {name}.exe", "", "可执行程序 (*.exe);;所有文件 (*)")
        if path:
            getattr(self, name).setText(path)
            if name == "ffmpeg":
                self.autofill_probe()
            self.testRequested.emit(self.ffmpeg.text(), self.ffprobe.text())

    def autofill_probe(self):
        candidate = sibling_probe(self.ffmpeg.text())
        if candidate:
            self.ffprobe.setText(candidate)

    def find(self):
        ffmpeg, ffprobe = find_tools()
        self.ffmpeg.setText(ffmpeg)
        self.ffprobe.setText(ffprobe)
        if ffmpeg:
            self.testRequested.emit(ffmpeg, ffprobe)
        else:
            self.report.setPlainText("系统 PATH 中未找到 FFmpeg。请手动选择本地 ffmpeg.exe，无需修改环境变量。")

    def select_output(self):
        path = QFileDialog.getExistingDirectory(self, "默认输出目录", self.output.text())
        if path:
            self.output.setText(path)

    def values(self, previous):
        return replace(previous, ffmpeg=self.ffmpeg.text().strip(), ffprobe=self.ffprobe.text().strip(),
                       output_dir=self.output.text().strip(), concurrency=self.concurrency.value(),
                       preserve_structure=self.structure.isChecked(), auto_open=self.auto_open.isChecked(), theme=self.theme.currentData())

    def set_busy(self, busy):
        for widget in [self.ffmpeg, self.ffprobe, *self.path_buttons]:
            widget.setEnabled(not busy)
        self.test.setEnabled(not busy)
        self.auto_setup.setEnabled(not busy)
        self.cancel_setup.setEnabled(busy)
