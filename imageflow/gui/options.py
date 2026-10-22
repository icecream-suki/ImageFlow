from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QFormLayout, QLabel, QComboBox, QSpinBox,
                               QDoubleSpinBox, QCheckBox, QLineEdit, QPushButton, QColorDialog,
                               QStackedWidget, QScrollArea, QHBoxLayout)

from ..models import Options
from .rules import RulesEditor
import math


def combo(items):
    widget = QComboBox()
    for label, value in items:
        widget.addItem(label, value)
    return widget


def spin(low, high, value):
    widget = QSpinBox()
    widget.setRange(low, high)
    widget.setValue(value)
    return widget


def decimal(low, high, value, suffix=""):
    widget = QDoubleSpinBox()
    widget.setRange(low, high)
    widget.setValue(value)
    widget.setSuffix(suffix)
    return widget


def check(text, checked=False):
    widget = QCheckBox(text)
    widget.setChecked(checked)
    return widget


def note(text):
    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setObjectName("note")
    return widget


class OptionsPanel(QWidget):
    changed = Signal()
    cropEdited = Signal(object)
    ratioChanged = Signal(object)

    def __init__(self, settings):
        super().__init__()
        layout = QVBoxLayout(self)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.warning = note("")
        layout.addWidget(self.warning)
        self.make_convert(settings)
        self.make_edit()
        self.make_quality()
        self.make_animation(settings)
        self.state_controls = {name: getattr(self, name) for name in (
            "resize", "width", "height", "percent", "presets", "only_shrink", "interpolation", "crop_enabled", "ratio",
            "cx", "cy", "cw", "ch", "rotation", "hflip", "vflip", "quality", "lossless", "strip", "alpha",
            "background", "first_frame", "anim_preset", "keep_fps", "fps", "loops", "colors", "dither", "threshold", "limit")}
        self.restore_state(settings.processing)
        for widget in self.state_controls.values():
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self.changed)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(self.changed)
            elif isinstance(widget, QLineEdit):
                widget.textChanged.connect(self.changed)
            else:
                widget.valueChanged.connect(self.changed)
        for widget in (self.image_format, self.animation_format):
            widget.currentIndexChanged.connect(self.update_controls)
            widget.currentIndexChanged.connect(self.changed)
        self.rules_editor.changed.connect(self.update_controls)
        self.rules_editor.changed.connect(self.changed)
        self.update_controls()

    def page(self):
        contents = QWidget()
        form = QFormLayout(contents)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(contents)
        self.pages.addWidget(scroll)
        return form

    def make_convert(self, settings):
        form = self.page()
        form.addRow(note("按输入格式与静态 / 动画类型自动选择输出。"))
        self.image_format = combo([(x.upper(), x) for x in ["png", "jpeg", "webp", "bmp", "tiff"]])
        self.animation_format = combo([("GIF", "gif"), ("APNG", "apng"), ("动态 WebP", "webp")])
        self.image_format.setCurrentIndex(max(0, self.image_format.findData(settings.image_format)))
        self.animation_format.setCurrentIndex(max(0, self.animation_format.findData(settings.animation_format)))
        form.addRow("默认图片格式", self.image_format)
        form.addRow("默认动画格式", self.animation_format)
        form.addRow(note("自定义分流规则 · 从上到下匹配，首条命中生效；未命中则使用上方默认格式。输入类型按文件内容识别。"))
        self.rules_editor = RulesEditor(settings.routing_rules)
        form.addRow(self.rules_editor)
        self.first_frame = check("允许动画仅导出首帧")
        form.addRow(self.first_frame)
        form.addRow(note("普通 PNG、JPEG、BMP、TIFF 只导出一张图片。未勾选时会阻止动画转换为这些格式。TGS 暂不支持。"))

    def make_edit(self):
        form = self.page()
        self.resize = combo([("保留原始尺寸", "original"), ("保持比例 · 放入宽高边界", "fit"),
                             ("指定宽高 · 允许变形", "exact"), ("按百分比", "percent")])
        self.width, self.height = spin(1, 32768, 512), spin(1, 32768, 512)
        self.percent = decimal(.1, 1000, 100, " %")
        self.only_shrink = check("只缩小，不放大", True)
        self.presets = combo([("选择尺寸预设", 0), ("512 × 512", 512), ("320 × 320", 320), ("256 × 256", 256),
                              ("1920 × 1080", (1920, 1080)), ("1280 × 720", (1280, 720))])
        self.presets.currentIndexChanged.connect(self.apply_size)
        self.resize.currentIndexChanged.connect(self.resize_controls)
        self.interpolation = combo([("Lanczos · 高质量", "lanczos"), ("双三次", "bicubic"), ("双线性", "bilinear"), ("最近邻 · 像素画", "neighbor")])
        form.addRow("缩放模式", self.resize)
        form.addRow("尺寸预设", self.presets)
        form.addRow("宽度上限 / 宽", self.width)
        form.addRow("高度上限 / 高", self.height)
        form.addRow("缩放比例", self.percent)
        form.addRow(self.only_shrink)
        form.addRow("插值算法", self.interpolation)
        self.crop_enabled = check("启用裁剪 · 可在预览中拖选")
        form.addRow(self.crop_enabled)
        self.ratio = combo([("自由比例", None), ("1:1", 1.), ("4:3", 4/3), ("16:9", 16/9), ("9:16", 9/16)])
        form.addRow("鼠标裁剪比例", self.ratio)
        self.ratio.currentIndexChanged.connect(lambda: self.ratioChanged.emit(self.ratio.currentData()))
        self.cx, self.cy, self.cw, self.ch = spin(0, 32768, 0), spin(0, 32768, 0), spin(1, 32768, 256), spin(1, 32768, 256)
        for label, widget in [("原图 X", self.cx), ("原图 Y", self.cy), ("裁剪宽", self.cw), ("裁剪高", self.ch)]:
            form.addRow(label, widget)
            widget.valueChanged.connect(self.emit_crop)
        self.crop_enabled.toggled.connect(self.emit_crop)
        self.rotation = decimal(-360, 360, 0, " °")
        form.addRow("顺时针旋转", self.rotation)
        buttons = QWidget()
        row = QHBoxLayout(buttons)
        row.setContentsMargins(0, 0, 0, 0)
        for title, angle in [("↶ 90°", -90), ("↷ 90°", 90)]:
            button = QPushButton(title)
            button.clicked.connect(lambda _, a=angle: self.rotation.setValue((self.rotation.value()+a) % 360))
            row.addWidget(button)
        form.addRow(buttons)
        self.hflip, self.vflip = check("水平翻转"), check("垂直翻转")
        form.addRow(self.hflip)
        form.addRow(self.vflip)
        form.addRow(note("操作顺序：原图裁剪 → 缩放 → 旋转 → 翻转。批量裁剪使用相同像素坐标，超出某张图片边界时该任务会报告错误。"))
        self.resize_controls()

    def make_quality(self):
        form = self.page()
        self.quality = spin(1, 100, 85)
        self.lossless = check("WebP 无损编码")
        self.strip = check("删除输出元数据", True)
        self.alpha = check("保留透明背景（格式支持时）", True)
        self.background = QLineEdit("#ffffff")
        color = QPushButton("选择填充背景色…")
        color.clicked.connect(self.choose_color)
        form.addRow("JPEG / WebP 质量", self.quality)
        form.addRow(self.lossless)
        form.addRow(self.alpha)
        form.addRow("填充颜色", self.background)
        form.addRow(color)
        form.addRow(self.strip)
        form.addRow(note("无损编码：编码不再丢失当前像素。\n无损格式转换：还需目标格式能表达源像素，且未缩放、旋转、丢弃透明度。\n有损压缩：JPEG、有损 WebP 或 GIF 调色板量化会损失信息。\n输出 PNG 不会恢复此前已损失的细节。"))
        form.addRow(note("FFmpeg 对 ICC、EXIF 和其他元数据的保留并不完整；取消删除仅作尽力保留。此版本以像素坐标处理原图，不自动应用 EXIF 方向。"))

    def make_animation(self, settings):
        form = self.page()
        self.anim_preset = combo([(x, x) for x in ["画质优先", "平衡模式", "体积优先", "自定义"]])
        self.anim_preset.setCurrentText(settings.compression)
        self.keep_fps = check("保留原始逐帧时长", True)
        self.fps = decimal(1, 60, 20, " fps")
        self.loops = spin(0, 65535, 0)
        self.loops.setSpecialValueText("无限循环")
        self.colors = spin(4, 256, 256)
        self.dither = combo([("Sierra 2-4A", "sierra2_4a"), ("Bayer", "bayer"), ("Floyd–Steinberg", "floyd_steinberg"), ("无抖动", "none")])
        self.threshold = spin(0, 255, 128)
        self.limit = spin(0, 1_000_000, 0)
        self.limit.setSpecialValueText("不限制")
        self.limit.setSuffix(" KB")
        form.addRow("GIF 预设", self.anim_preset)
        form.addRow(self.keep_fps)
        form.addRow("输出帧率", self.fps)
        form.addRow("总播放次数（含首遍）", self.loops)
        form.addRow("GIF 最大颜色数", self.colors)
        form.addRow("GIF 抖动", self.dither)
        form.addRow("GIF 透明度阈值", self.threshold)
        form.addRow("GIF 体积上限", self.limit)
        form.addRow(note("GIF 每帧最多 256 色，只能表达完全透明或完全不透明。半透明边缘可能有锯齿；APNG 和动态 WebP 更适合保留半透明。\n体积限制最多尝试 7 次，逐步降低尺寸、帧率和色数；达不到限制时报告失败。"))
        self.keep_fps.toggled.connect(lambda value: self.fps.setEnabled(not value))
        self.anim_preset.currentIndexChanged.connect(self.apply_anim_preset)
        self.apply_anim_preset()
        for widget in (self.fps, self.colors, self.threshold, self.limit):
            widget.valueChanged.connect(self.custom_preset)
        self.keep_fps.clicked.connect(self.custom_preset)
        self.dither.activated.connect(self.custom_preset)

    def custom_preset(self, *args):
        self.anim_preset.blockSignals(True)
        self.anim_preset.setCurrentText("自定义")
        self.anim_preset.blockSignals(False)

    def apply_anim_preset(self):
        mode = self.anim_preset.currentText()
        if mode == "自定义":
            return
        widgets = [self.fps, self.colors, self.threshold, self.limit, self.dither, self.keep_fps]
        for widget in widgets:
            widget.blockSignals(True)
        self.keep_fps.setChecked(mode == "画质优先")
        self.fps.setValue(20 if mode != "体积优先" else 12)
        self.colors.setValue(128 if mode == "体积优先" else 256)
        self.dither.setCurrentIndex(1 if mode == "体积优先" else 0)
        self.threshold.setValue(128)
        self.limit.setValue(0)
        for widget in widgets:
            widget.blockSignals(False)
        self.fps.setEnabled(not self.keep_fps.isChecked())
        self.changed.emit()

    def apply_size(self):
        value = self.presets.currentData()
        if value:
            w, h = value if isinstance(value, tuple) else (value, value)
            self.width.setValue(w)
            self.height.setValue(h)
            self.resize.setCurrentIndex(1)

    def resize_controls(self):
        mode = self.resize.currentData()
        self.width.setEnabled(mode in {"fit", "exact"})
        self.height.setEnabled(mode in {"fit", "exact"})
        self.percent.setEnabled(mode == "percent")

    def update_controls(self):
        if not hasattr(self, "lossless"):
            return
        outputs = {self.image_format.currentData(), self.animation_format.currentData()}
        outputs.update(r["target"] for r in self.rules_editor.rules() if r["enabled"])
        self.quality.setEnabled(bool(outputs & {"jpeg", "webp"}))
        self.lossless.setEnabled("webp" in outputs)
        for widget in [self.colors, self.dither, self.threshold, self.limit, self.anim_preset]:
            widget.setEnabled("gif" in outputs)
        self.warning.setText("JPEG / BMP 不保留透明度，将使用所选背景色填充。" if outputs & {"jpeg", "bmp"} else "")

    def choose_color(self):
        color = QColorDialog.getColor(parent=self, title="透明区域填充颜色")
        if color.isValid():
            self.background.setText(color.name())

    def emit_crop(self):
        self.cropEdited.emit(tuple(w.value() for w in (self.cx, self.cy, self.cw, self.ch)) if self.crop_enabled.isChecked() else None)

    def set_crop(self, values):
        for widget, value in zip((self.cx, self.cy, self.cw, self.ch), values):
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        self.changed.emit()

    def snapshot(self):
        values = {}
        for name, widget in self.state_controls.items():
            values[name] = (widget.currentData() if isinstance(widget, QComboBox) else
                            widget.isChecked() if isinstance(widget, QCheckBox) else
                            widget.text() if isinstance(widget, QLineEdit) else widget.value())
        return values

    def restore_state(self, values):
        for widget in self.state_controls.values():
            widget.blockSignals(True)
        try:
            for name, value in values.items():
                widget = self.state_controls.get(name)
                if isinstance(widget, QComboBox):
                    if name == "presets" and isinstance(value, list):
                        value = tuple(value)
                    index = widget.findData(value)
                    if index >= 0:
                        widget.setCurrentIndex(index)
                elif isinstance(widget, QCheckBox) and type(value) is bool:
                    widget.setChecked(value)
                elif isinstance(widget, QLineEdit) and isinstance(value, str):
                    widget.setText(value)
                elif isinstance(widget, (QSpinBox, QDoubleSpinBox)) and type(value) in {int, float} and math.isfinite(value):
                    widget.setValue(int(value) if isinstance(widget, QSpinBox) else value)
        finally:
            for widget in self.state_controls.values():
                widget.blockSignals(False)
        self.resize_controls()
        self.fps.setEnabled(not self.keep_fps.isChecked())

    def options(self):
        return Options(auto_route=True, image_format=self.image_format.currentData(),
                       animation_format=self.animation_format.currentData(), routing_rules=self.rules_editor.rules(), resize=self.resize.currentData(),
                       width=self.width.value(), height=self.height.value(), percent=self.percent.value(),
                       only_shrink=self.only_shrink.isChecked(), interpolation=self.interpolation.currentData(),
                       crop=tuple(w.value() for w in (self.cx, self.cy, self.cw, self.ch)) if self.crop_enabled.isChecked() else None,
                       rotation=self.rotation.value(), hflip=self.hflip.isChecked(), vflip=self.vflip.isChecked(),
                       quality=self.quality.value(), lossless_webp=self.lossless.isChecked(), strip_metadata=self.strip.isChecked(),
                       preserve_alpha=self.alpha.isChecked(), background=self.background.text().strip(),
                       fps=None if self.keep_fps.isChecked() else self.fps.value(), loops=self.loops.value(),
                       colors=self.colors.value(), dither=self.dither.currentData(), alpha_threshold=self.threshold.value(),
                       gif_limit_kb=self.limit.value(), allow_first_frame=self.first_frame.isChecked())
