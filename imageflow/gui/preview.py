from dataclasses import dataclass
from collections import OrderedDict
import threading

from PIL import Image, ImageOps
from PySide6.QtCore import Qt, QRectF, Signal, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QImage
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel

from ..process import stream_frames
from ..models import Cancelled


@dataclass
class PreviewData:
    frames: list[bytes]
    delays: list[int]
    width: int
    height: int
    note: str = ""
    frame_size: tuple[int, int] | None = None


class PreviewCache:
    def __init__(self, budget=128_000_000):
        self.budget = budget
        self.items = OrderedDict()

    @staticmethod
    def key(media, caps):
        stat = media.path.stat()
        return (str(media.path.resolve()), stat.st_mtime_ns, stat.st_size, caps.ffmpeg)

    def get(self, key):
        if key in self.items:
            self.items.move_to_end(key)
            return self.items[key]

    def put(self, key, data):
        self.items[key] = data
        self.items.move_to_end(key)
        while len(self.items) > 8 or sum(sum(map(len, d.frames)) for d in self.items.values()) > self.budget:
            self.items.popitem(last=False)


def load_preview(media, caps, cancel=None, on_first=lambda _: None):
    cancel = cancel or threading.Event()
    if cancel.is_set():
        raise Cancelled("预览已取消。")
    if media.format == "WEBM":
        scale = min(1, 400 / max(media.width, media.height))
        w, h = max(1, round(media.width * scale)), max(1, round(media.height * scale))
        fps = min(20, media.fps or 20)
        data = PreviewData([], [], media.width, media.height,
                           "预览最高 400 像素 / 20 fps；输出按处理参数保持原始画质。", (w, h))
        args = [caps.ffmpeg, "-v", "error", "-nostdin", "-threads", "2"]
        decoder = "libvpx-vp9" if media.codec == "vp9" else "libvpx"
        if media.alpha and decoder in caps.decoders:
            args += ["-c:v", decoder]
        elif media.alpha:
            raise ValueError("此 FFmpeg 缺少 Alpha 解码器，无法可靠预览透明贴纸。")
        args += ["-i", str(media.path), "-an", "-vf", f"fps={fps},scale={w}:{h}",
                 "-frames:v", "64", "-threads", "2", "-pix_fmt", "rgba", "-f", "rawvideo", "pipe:1"]

        def frame_ready(frame):
            data.frames.append(frame)
            data.delays.append(max(10, round(1000 / fps)))
            if len(data.frames) == 1:
                on_first(PreviewData(data.frames.copy(), data.delays.copy(), media.width, media.height, data.note, (w, h)))

        stream_frames(args, w*h*4, cancel, frame_ready)
        return data
    return _pillow_preview(media.path, media, cancel, on_first)


def _pillow_preview(path, media, cancel, on_first):
    frames, delays = [], []
    pixels = 0
    note = "预览已缩略；裁剪坐标始终按原图计算。"
    with Image.open(path) as im:
        start = 1 if im.info.get("default_image", False) else 0
        count = getattr(im, "n_frames", 1)
        for index in range(start, count):
            if cancel.is_set():
                raise Cancelled("预览已取消。")
            im.seek(index)
            image = im.convert("RGBA")
            delay = im.info.get("duration", 100) or 100
            image.thumbnail((700, 500), Image.Resampling.LANCZOS)
            if frames and (pixels + image.width * image.height > 16_000_000 or len(frames) >= 300):
                note = "预览只加载前 300 帧或 64MB 像素；完整动画仍参与转换。"
                break
            pixels += image.width * image.height
            frames.append(image.tobytes())
            delays.append(max(10, round(delay)))
            if len(frames) == 1:
                on_first(PreviewData(frames.copy(), delays.copy(), media.width, media.height, note, image.size))
    return PreviewData(frames, delays, media.width, media.height, note, image.size)


class CropCanvas(QWidget):
    cropChanged = Signal(tuple)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(260, 140)
        self.pixmap = QPixmap()
        self.original = (1, 1)
        self.crop = None
        self.origin = None
        self.ratio = None
        self.cropping = False
        self.setToolTip("在尺寸与裁剪页启用裁剪后，用鼠标拖动选择原图区域。")

    def image_rect(self):
        if self.pixmap.isNull():
            return QRectF()
        ratio = min((self.width()-24) / self.pixmap.width(), (self.height()-24) / self.pixmap.height())
        w, h = self.pixmap.width()*ratio, self.pixmap.height()*ratio
        return QRectF((self.width()-w)/2, (self.height()-h)/2, w, h)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#242936"))
        area = self.image_rect()
        if area.isEmpty():
            painter.setPen(QColor("#a7b2c6"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "拖入图片，开始本地处理\nPNG · JPEG · WebP · GIF · APNG · WebM 贴纸")
            return
        painter.save()
        painter.setClipRect(area)
        for y in range(int(area.top()), int(area.bottom())+16, 16):
            for x in range(int(area.left()), int(area.right())+16, 16):
                parity = ((x-int(area.left()))//16 + (y-int(area.top()))//16) % 2
                painter.fillRect(x, y, 16, 16, QColor("#c9cdd4" if parity else "#eef0f3"))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(area.toRect(), self.pixmap)
        painter.restore()
        if self.crop:
            x, y, w, h = self.crop
            ow, oh = self.original
            selection = QRectF(area.x()+x/ow*area.width(), area.y()+y/oh*area.height(), w/ow*area.width(), h/oh*area.height())
            painter.setPen(QPen(QColor("#38bdf8"), 2))
            painter.setBrush(QColor(56, 189, 248, 35))
            painter.drawRect(selection)

    def coordinate(self, position):
        area = self.image_rect()
        if area.isEmpty():
            return 0, 0
        return (max(0, min(self.original[0], round((position.x()-area.x())/area.width()*self.original[0]))),
                max(0, min(self.original[1], round((position.y()-area.y())/area.height()*self.original[1]))))

    def mousePressEvent(self, event):
        if self.cropping and event.button() == Qt.MouseButton.LeftButton and self.image_rect().contains(event.position()):
            self.origin = self.coordinate(event.position())

    def mouseMoveEvent(self, event):
        if self.origin is None:
            return
        x, y = self.coordinate(event.position())
        ox, oy = self.origin
        w, h = abs(x-ox), abs(y-oy)
        if self.ratio:
            w = min(w, int(h*self.ratio))
            h = int(w/self.ratio)
        if w > 0 and h > 0:
            self.crop = (ox if x >= ox else ox-w, oy if y >= oy else oy-h, w, h)
            self.cropChanged.emit(self.crop)
            self.update()

    def mouseReleaseEvent(self, event):
        self.origin = None


class PreviewWidget(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.caption = QLabel("原图预览")
        layout.addWidget(self.caption)
        self.canvas = CropCanvas()
        layout.addWidget(self.canvas, 1)
        controls = QHBoxLayout()
        self.play = QPushButton("播放 / 暂停")
        self.restart = QPushButton("重新播放")
        self.frame_label = QLabel("尚未选择文件")
        controls.addWidget(self.play)
        controls.addWidget(self.restart)
        controls.addWidget(self.frame_label, 1)
        layout.addLayout(controls)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.next_frame)
        self.play.clicked.connect(self.toggle)
        self.restart.clicked.connect(self.replay)
        self.data = None
        self.index = 0

    def clear(self):
        self.timer.stop()
        self.data = None
        self.canvas.pixmap = QPixmap()
        self.canvas.crop = None
        self.canvas.update()

    def set_data(self, data):
        self.clear()
        self.data = data
        self.canvas.original = (data.width, data.height)
        self.index = 0
        self.note.setText(data.note)
        self.show_frame()
        self.play.setEnabled(len(data.frames) > 1)
        self.restart.setEnabled(len(data.frames) > 1)

    def show_frame(self):
        if self.data and self.data.frames:
            if self.data.frame_size:
                w, h = self.data.frame_size
                im = QImage(self.data.frames[self.index], w, h, w*4, QImage.Format.Format_RGBA8888)
                self.canvas.pixmap = QPixmap.fromImage(im.copy())
            else:
                self.canvas.pixmap.loadFromData(self.data.frames[self.index])
            self.canvas.update()
            self.frame_label.setText(f"帧 {self.index+1} / {len(self.data.frames)}")

    def next_frame(self):
        self.index = (self.index + 1) % len(self.data.frames)
        self.show_frame()
        self.timer.start(self.data.delays[self.index])

    def toggle(self):
        if not self.data or len(self.data.frames) < 2:
            return
        if self.timer.isActive():
            self.timer.stop()
        else:
            self.timer.start(self.data.delays[self.index])

    def replay(self):
        if self.data and self.data.frames:
            self.index = 0
            self.show_frame()
            self.timer.start(self.data.delays[0])
