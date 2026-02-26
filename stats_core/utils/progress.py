from __future__ import annotations

import logging
from contextlib import AbstractContextManager

from tqdm import tqdm


class TqdmLoggingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            tqdm.write(msg)
        except Exception:
            self.handleError(record)


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
    ) -> None:
        self.logger = logger or logging.getLogger("report.progress")
        self._enabled = enabled
        self._total = max(int(total_steps or 0), 1)
        self.current = 0
        if self._enabled:
            self._bar = tqdm(
                total=self._total,
                desc=report_name,
                dynamic_ncols=True,
                leave=True,
            )
        else:
            self._bar = None

    def set_total(self, total_steps: int) -> None:
        self._total = max(int(total_steps), 1)
        if self._bar is not None:
            self._bar.total = self._total
            self._bar.refresh()

    def step(self, name: str) -> ProgressStep:
        return ProgressStep(self, name)

    def advance(self, n: int = 1) -> None:
        self.current += n
        if self._bar is not None:
            self._bar.update(n)

    def close(self) -> None:
        if self._bar is not None:
            self._bar.close()


class NoopProgressManager(ProgressManager):
    def __init__(self) -> None:
        super().__init__(total_steps=1, report_name="report", enabled=False)

    def set_total(self, total_steps: int) -> None:
        self._total = max(int(total_steps), 1)

    def advance(self, n: int = 1) -> None:
        self.current += n
