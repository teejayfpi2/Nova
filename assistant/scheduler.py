"""Background scheduler that fires due reminders."""

from __future__ import annotations

import threading
from typing import Callable

from .memory import Memory, Reminder


class Scheduler:
    def __init__(self, memory: Memory, interval: float = 15.0) -> None:
        self.memory = memory
        self.interval = interval
        self._listeners: list[Callable[[Reminder], None]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def on_fire(self, callback: Callable[[Reminder], None]) -> None:
        self._listeners.append(callback)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="nova-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                for reminder in self.memory.due_reminders():
                    self.memory.complete_reminder(reminder.id)
                    for listener in self._listeners:
                        try:
                            listener(reminder)
                        except Exception:  # noqa: BLE001 - never kill the scheduler
                            pass
            except Exception:  # noqa: BLE001
                pass
            self._stop.wait(self.interval)
