from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class WorkerSignals(QObject):
    result = Signal(object)
    partial = Signal(object)
    progress = Signal(str)
    error = Signal(str)
    finished = Signal()


class Worker(QRunnable):
    def __init__(self, function, with_signals=False):
        super().__init__()
        self.function = function
        self.with_signals = with_signals
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            self.signals.result.emit(self.function(self.signals) if self.with_signals else self.function())
        except Exception as exc:
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()
