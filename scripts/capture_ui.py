"""Generate reproducible, real-widget screenshots for release QA."""
from pathlib import Path
import os
import sys
import time
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from imageflow.config import ConfigStore
from imageflow.capabilities import inspect
from imageflow.probe import probe
from imageflow.gui.preview import load_preview
from imageflow.gui.main import MainWindow
from imageflow.models import Task, Options
from imageflow.engine import Engine
from imageflow.queue import TaskQueue

root = Path(__file__).resolve().parent.parent
out = root / 'artifacts'
out.mkdir(exist_ok=True)
caps = inspect(os.environ['IMAGEFLOW_FFMPEG'], os.environ.get('IMAGEFLOW_FFPROBE', ''))
frames = []
for i in range(12):
    im = Image.new('RGBA', (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    draw.rounded_rectangle((90, 80+i*3, 422, 412+i*3), radius=78, fill=(40, 125, 230, 255))
    draw.rounded_rectangle((117, 107+i*3, 395, 385+i*3), radius=60, fill=(83, 178, 246, 255))
    draw.ellipse((165, 190+i*3, 195, 230+i*3), fill='white')
    draw.ellipse((317, 190+i*3, 347, 230+i*3), fill='white')
    draw.arc((200, 218+i*3, 312, 305+i*3), 0, 180, fill='white', width=13)
    draw.ellipse((55+i*5, 47, 100+i*5, 92), fill=(255, 190, 70, 255))
    frames.append(im)
source = out / '示例动态贴纸.webp'
frames[0].save(source, save_all=True, append_images=frames[1:], duration=80, loop=0, lossless=True)
frames[0].save(out / '示例透明图片.png')
app = QApplication([])
for name in ['msyh.ttc', 'msyhbd.ttc']:
    font = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / name
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
app.setStyle('Fusion')
profile = tempfile.TemporaryDirectory(prefix='imageflow-ui-')
window = MainWindow(ConfigStore(Path(profile.name)))
window.caps = caps
window.statusBar().showMessage('FFmpeg 已就绪 · 所有图片均在本地处理')
window.settings_page.ffmpeg.setText(caps.ffmpeg)
window.settings_page.ffprobe.setText(caps.ffprobe)
window.settings_page.report.setPlainText(caps.report())
media = probe(source, caps.ffprobe)
static = probe(out / '示例透明图片.png', caps.ffprobe)
window.imports = [(source, out, media, ''), (static.path, out, static, '')]
window.refresh_imports()
window.options.rules_editor.add_rule()
window.save_settings()
window.options.resize.setCurrentIndex(1)
window.output.setText(str(out / 'output'))
window.settings_page.theme.setCurrentText('浅色')
window.save_settings()
window.show()
window.nav.setCurrentRow(0)
window.preview.set_data(load_preview(media, caps))
window.info.setText('示例动态贴纸.webp · 512 × 512 · 12 帧\n透明区域：有　帧率：12.5 fps　时长：0.960 秒')
app.processEvents()
window.grab().save(str(out / 'ui-light.png'))
window.settings.theme = '深色'
window.settings_page.theme.setCurrentText('深色')
window.apply_theme()
app.processEvents()
window.grab().save(str(out / 'ui-dark.png'))
window.resize(1000, 720)
app.processEvents()
window.grab().save(str(out / 'ui-minimum.png'))
window.resize(1260, 880)
window.queue = TaskQueue(Engine(caps, log_dir=out / 'qa-logs'), changed=window.bridge.taskChanged.emit)
for info in [media, static]:
    window.queue.add(Task(info, Options(telegram=True), out / 'output'))
window.start_queue()
while window.queue.active:
    app.processEvents()
    time.sleep(.02)
app.processEvents()
window.nav.setCurrentRow(4)
app.processEvents()
window.grab().save(str(out / 'ui-queue.png'))
window.nav.setCurrentRow(5)
app.processEvents()
window.grab().save(str(out / 'ui-settings.png'))
window.close()
while window.workers or window.isVisible():
    app.processEvents()
    time.sleep(.01)
profile.cleanup()
print(f'Screenshots saved to {out}')
