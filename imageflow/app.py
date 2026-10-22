import logging
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from .config import ConfigStore
from .gui.main import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("ImageFlow")
    app.setOrganizationName("ImageFlow")
    app.setStyle("Fusion")
    if "--smoke-test" in sys.argv:
        from .smoke import run_smoke
        index = sys.argv.index("--smoke-test")
        return run_smoke(app, sys.argv[index + 1])
    try:
        store = ConfigStore()
        logging.basicConfig(filename=store.directory / "application.log", level=logging.INFO,
                            encoding="utf-8", format="%(asctime)s %(levelname)s %(message)s")
        def exception_hook(kind, value, tb):
            logging.error("Unhandled GUI error", exc_info=(kind, value, tb))
            QMessageBox.critical(None, "ImageFlow", f"操作未完成：{value}\n详细日志：{store.directory / 'application.log'}")
        sys.excepthook = exception_hook
        window = MainWindow(store)
        window.show()
        return app.exec()
    except Exception as exc:
        QMessageBox.critical(None, "ImageFlow 启动失败", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
