import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt, QPoint

from imageflow.config import ConfigStore
from imageflow.gui.main import MainWindow
from imageflow.gui.preview import load_preview, PreviewCache
from imageflow.models import State
from imageflow.probe import probe

pytestmark = pytest.mark.gui


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


def wait_until(app, condition, timeout=20):
    start = time.monotonic()
    while not condition():
        app.processEvents()
        QTest.qWait(20)
        assert time.monotonic() - start < timeout


def test_window_navigation_and_theme(app, tmp_path):
    window = MainWindow(ConfigStore(tmp_path))
    window.show()
    for index in range(6):
        window.nav.setCurrentRow(index)
        app.processEvents()
        assert window.stack.currentIndex() == (0 if index < 4 else index - 3)
    window.settings.theme = "深色"
    window.apply_theme()
    window.resize(1000, 720)
    app.processEvents()
    assert window.isVisible()
    window.close()


@pytest.mark.integration
def test_gui_real_workflow(app, caps, samples, tmp_path):
    window = MainWindow(ConfigStore(tmp_path / "config"))
    window.show()
    window.test_tools(caps.ffmpeg, caps.ffprobe)
    wait_until(app, lambda: window.caps is not None and not window.workers)
    window.import_paths([samples["webp"], samples["animated_webp"]])
    wait_until(app, lambda: len(window.imports) == 2 and not window.workers)
    window.options.image_format.setCurrentText("PNG")
    window.options.animation_format.setCurrentText("GIF")
    window.output.setText(str(tmp_path / "output"))
    window.enqueue()
    assert len(window.queue.tasks) == 2
    window.start_queue()
    wait_until(app, lambda: not window.queue.active)
    assert all(t.state == State.DONE for t in window.queue.tasks)
    assert window.task_table.rowCount() == 2
    # Real crop gesture uses original coordinates, even when displayed at a different size.
    window.nav.setCurrentRow(1)
    window.file_table.selectRow(0)
    wait_until(app, lambda: not window.workers)
    window.options.crop_enabled.setChecked(True)
    canvas = window.preview.canvas
    area = canvas.image_rect()
    QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=area.center().toPoint())
    QTest.mouseMove(canvas, ((area.center()+area.bottomRight())/2).toPoint())
    QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton)
    assert canvas.crop is not None
    window.close()
    wait_until(app, lambda: not window.isVisible())


def test_autosave_restart_rules_and_controls(app, tmp_path):
    store = ConfigStore(tmp_path)
    window = MainWindow(store)
    window.show()
    assert not hasattr(window, "filter") and not hasattr(window.options, "format")
    assert not hasattr(window.options, "telegram") and not hasattr(window.settings_page, "image")
    window.options.image_format.setCurrentText("WEBP")
    window.options.animation_format.setCurrentText("APNG")
    window.options.rules_editor.add_rule()
    window.options.rules_editor.table.cellWidget(0, 3).setCurrentText("WEBP")
    window.options.width.setValue(320)
    window.options.resize.setCurrentIndex(1)
    window.options.quality.setValue(77)
    window.options.crop_enabled.setChecked(True)
    window.options.set_crop((1, 2, 30, 40))
    window.options.background.setText("#123456")
    window.options.keep_fps.setChecked(False)
    window.options.fps.setValue(15)
    window.settings_page.theme.setCurrentText("深色")
    window.settings_page.concurrency.setValue(3)
    window.output.setText(str(tmp_path / "outputs"))
    window.recursive.setChecked(True)
    window.structure.setChecked(True)
    window.conflict.setCurrentIndex(1)
    wait_until(app, lambda: store.path.exists() and store.load().processing.get("quality") == 77)
    assert store.load().routing_rules[0]["target"] == "webp"
    assert window.settings_page.output.text() == window.output.text()
    # Closing immediately after an edit must flush the debounce timer.
    window.options.rotation.setValue(90)
    window.close()
    restored = MainWindow(store)
    assert restored.options.image_format.currentData() == "webp"
    assert restored.options.animation_format.currentData() == "apng"
    assert restored.options.snapshot() == window.options.snapshot()
    assert restored.options.rules_editor.rules() == window.options.rules_editor.rules()
    assert restored.recursive.isChecked() and restored.structure.isChecked()
    assert restored.conflict.currentData() == "skip"
    assert restored.settings_page.theme.currentText() == "深色"
    assert restored.settings_page.concurrency.value() == 3
    restored.close()


def test_system_theme_live_and_manual_override(app, tmp_path):
    from PySide6.QtGui import QPalette
    window = MainWindow(ConfigStore(tmp_path))
    window.settings_page.theme.setCurrentText("跟随系统")
    window.save_settings()
    window.system_theme_changed(Qt.ColorScheme.Dark)
    assert window.palette().color(QPalette.ColorRole.Window).name() == "#151b27"
    window.system_theme_changed(Qt.ColorScheme.Light)
    assert window.palette().color(QPalette.ColorRole.Window).name() == "#f4f6fa"
    window.settings_page.theme.setCurrentText("深色")
    window.save_settings()
    window.system_theme_changed(Qt.ColorScheme.Light)
    assert window.palette().color(QPalette.ColorRole.Window).name() == "#151b27"
    window.close()


@pytest.mark.integration
def test_preview_cache_and_autosave_preserves_selection(app, caps, samples, tmp_path, monkeypatch):
    import imageflow.gui.main as main
    window = MainWindow(ConfigStore(tmp_path / "config"))
    window.caps = caps
    media = probe(samples["animated_webp"], caps.ffprobe)
    window.imports = [(media.path, media.path.parent, media, "")]
    window.refresh_imports()
    window.file_table.selectRow(0)
    wait_until(app, lambda: not window.workers)
    assert len(window.preview.data.frames) == 4
    def unexpected(*a, **kw):
        pytest.fail("A cached preview must not decode again")
    monkeypatch.setattr(main, "load_preview", unexpected)
    window.show_media(media, "原图预览")
    assert len(window.preview.data.frames) == 4 and not window.workers
    window.options.rules_editor.add_rule()
    window.options.rules_editor.table.cellWidget(0, 3).setCurrentText("APNG")
    window.save_settings()
    assert window.selected_rows(window.file_table) == [0]
    assert "APNG" in window.file_table.item(0, 4).text()
    window.close()


@pytest.mark.integration
def test_oneclick_gui_saves_detected_paths(app, caps, tmp_path):
    window = MainWindow(ConfigStore(tmp_path))
    window.settings_page.ffmpeg.setText(caps.ffmpeg)
    window.setup_tools()
    wait_until(app, lambda: not window.workers)
    assert window.caps and window.store.load().ffprobe == caps.ffprobe
    assert window.settings_page.auto_setup.isEnabled()
    assert not window.settings_page.cancel_setup.isEnabled()
    window.close()
