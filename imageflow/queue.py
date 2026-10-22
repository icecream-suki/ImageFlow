from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import threading

from .models import State


class TaskQueue:
    """The UI owns task creation; worker callbacks are bridged via Qt signals."""
    def __init__(self, engine, concurrency=2, changed=lambda _: None):
        self.engine = engine
        self.changed = changed
        self.tasks = []
        self.concurrency = max(1, min(4, concurrency))
        self.pool = ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix="imageflow")
        self.futures = {}
        self.lock = threading.RLock()

    def add(self, task):
        with self.lock:
            # A task snapshot is independent of subsequent GUI edits.
            task.options = deepcopy(task.options)
            self.tasks.append(task)
            self.engine.allocator.protect([task.media.path])
        self.changed(task)

    def start(self):
        with self.lock:
            for task in self.tasks:
                if task.state == State.WAITING and task.id not in self.futures:
                    self.futures[task.id] = self.pool.submit(self.engine.execute, task, self.changed)

    def cancel_waiting(self):
        with self.lock:
            for task in self.tasks:
                if task.state == State.WAITING:
                    task.cancel.set()
                    future = self.futures.get(task.id)
                    if future:
                        future.cancel()
                    task.state = State.CANCELLED
                    self.changed(task)

    def stop(self):
        with self.lock:
            for task in self.tasks:
                if task.state in {State.WAITING, State.RUNNING}:
                    task.cancel.set()
            self.cancel_waiting()

    def retry_failed(self):
        with self.lock:
            for task in self.tasks:
                future = self.futures.get(task.id)
                if task.state == State.FAILED and (not future or future.done()):
                    task.cancel.clear()
                    task.state, task.progress, task.error = State.WAITING, 0, ""
                    self.futures.pop(task.id, None)
                    self.changed(task)
        self.start()

    @property
    def active(self):
        return any(not future.done() for future in self.futures.values())

    def set_concurrency(self, value):
        with self.lock:
            value = max(1, min(4, value))
            if self.active or value == self.concurrency:
                return
            self.pool.shutdown(wait=False)
            self.concurrency = value
            self.pool = ThreadPoolExecutor(max_workers=value, thread_name_prefix="imageflow")

    def shutdown(self):
        self.stop()
        self.pool.shutdown(wait=True, cancel_futures=True)
