from __future__ import annotations

import logging
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from contextlib import AbstractContextManager

from tqdm import tqdm


class TqdmLoggingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            if hasattr(sys.stderr, "isatty") and sys.stderr.isatty():
                tqdm.write(msg, file=sys.stderr)
            else:
                print(msg, file=sys.stderr)
            _refresh_active_bars()
            self.flush()
        except Exception:
            self.handleError(record)


def _refresh_active_bars() -> None:
    try:
        lock = tqdm.get_lock()
    except Exception:
        lock = None
    if lock:
        with lock:
            for bar in list(tqdm._instances):
                bar.refresh()
    else:
        for bar in list(tqdm._instances):
            bar.refresh()


@contextmanager
def tqdm_console_logging(root_logger: logging.Logger, formatter: logging.Formatter):
    tqdm_handler = TqdmLoggingHandler()
    tqdm_handler.setFormatter(formatter)

    console_handlers = [
        handler
        for handler in list(root_logger.handlers)
        if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler)
    ]
    for handler in console_handlers:
        root_logger.removeHandler(handler)
    root_logger.addHandler(tqdm_handler)

    try:
        yield
    finally:
        root_logger.removeHandler(tqdm_handler)
        for handler in console_handlers:
            if handler not in root_logger.handlers:
                root_logger.addHandler(handler)


class ProgressStep(AbstractContextManager["ProgressStep"]):
    def __init__(self, manager: "ProgressManager", name: str):
        self._manager = manager
        self._name = name

    def __enter__(self) -> "ProgressStep":
        self._manager.logger.info("Step started: %s", self._name)
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self._manager.logger.info("Step finished: %s", self._name)
        else:
            self._manager.logger.error("Step failed: %s", self._name)
        self._manager.advance(1)
        return False


class ProgressManager:
    def __init__(
        self,
        *,
        total_steps: int | None,
        report_name: str,
        logger: logging.Logger | None = None,
        enabled: bool = True,
        children_enabled: bool = True,
    ) -> None:
        self.logger = logger or logging.getLogger("report.progress")
        self._enabled = enabled
        self._children_enabled = children_enabled
        self._total = max(int(total_steps or 0), 1)
        self.current = 0
        self._lock = threading.RLock()
        self._children: list[ChildProgress] = []
        self._child_base_position = 1
        self._tty = bool(sys.stderr.isatty()) if enabled else False
        if self._enabled:
            tqdm.set_lock(threading.RLock())
            self._bar = tqdm(
                total=self._total,
                desc=report_name,
                position=0,
                dynamic_ncols=True,
                leave=True,
                file=sys.stderr,
                disable=not self._tty,
            )
        else:
            self._bar = None

    def set_total(self, total_steps: int) -> None:
        with self._lock:
            self._total = max(int(total_steps), 1)
            if self._bar is not None:
                self._bar.total = self._total
                self._bar.refresh()

    def step(self, name: str) -> ProgressStep:
        return ProgressStep(self, name)

    def advance(self, n: int = 1) -> None:
        with self._lock:
            self.current += n
            if self._bar is not None:
                self._bar.update(n)

    def close(self) -> None:
        for child in self._children:
            child.close()
        self._children = []
        if self._bar is not None:
            self._bar.close()

    def create_children(self, *, count: int, total: int | None, label: str) -> list["ChildProgress"]:
        if not self._enabled or not self._tty or not self._children_enabled or count <= 0:
            return []
        per_total = None if total is None else max(int(total), 1)
        children: list[ChildProgress] = []
        for idx in range(count):
            bar = tqdm(
                total=per_total,
                desc=f"{label} {idx + 1}",
                position=self._child_base_position + idx,
                dynamic_ncols=True,
                leave=False,
                file=sys.stderr,
            )
            children.append(ChildProgress(bar=bar))
        self._children.extend(children)
        return children


class NoopProgressManager(ProgressManager):
    def __init__(self) -> None:
        super().__init__(total_steps=1, report_name="report", enabled=False)

    def set_total(self, total_steps: int) -> None:
        with self._lock:
            self._total = max(int(total_steps), 1)

    def advance(self, n: int = 1) -> None:
        with self._lock:
            self.current += n


@dataclass
class ChildProgress:
    bar: tqdm

    def advance(self, n: int = 1) -> None:
        self.bar.update(n)

    def close(self) -> None:
        self.bar.close()
