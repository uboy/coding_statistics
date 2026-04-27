from __future__ import annotations

import logging
from unittest.mock import patch

import sys
from stats_core.utils.parallel import parallel_map
from stats_core.utils.progress import ProgressManager, TqdmLoggingHandler


class RecordingProgress:
    def __init__(self):
        self.current = 0

    def advance(self, n=1):
        self.current += n

    def create_children(self, **kwargs):
        return []


def test_tqdm_logging_handler_uses_tqdm_write():
    logger = logging.getLogger("tqdm-test")
    logger.setLevel(logging.INFO)
    handler = TqdmLoggingHandler()
    logger.addHandler(handler)
    try:
        with patch.object(sys.stderr, "isatty", return_value=True):
            with patch("stats_core.utils.progress.tqdm.write") as mock_write:
                logger.info("hello")
                assert mock_write.called
    finally:
        logger.removeHandler(handler)


def test_progress_manager_step_advances():
    logger = logging.getLogger("progress-test")
    logger.setLevel(logging.INFO)
    manager = ProgressManager(total_steps=1, report_name="report", logger=logger)
    with manager.step("Step 1"):
        pass
    assert manager.current == 1


def test_progress_manager_disables_visible_bar_when_not_tty():
    logger = logging.getLogger("progress-non-tty-test")
    logger.setLevel(logging.INFO)
    with patch.object(sys.stderr, "isatty", return_value=False):
        manager = ProgressManager(total_steps=1, report_name="report", logger=logger)
        try:
            assert manager._bar.disable is True
            manager.advance(1)
            assert manager.current == 1
        finally:
            manager.close()


def test_progress_manager_creates_child_bars():
    logger = logging.getLogger("progress-child-test")
    logger.setLevel(logging.INFO)
    with patch.object(sys.stderr, "isatty", return_value=True):
        manager = ProgressManager(total_steps=1, report_name="report", logger=logger)
        children = manager.create_children(count=2, total=4, label="worker")
        assert len(children) == 2
        children[0].advance(1)
        children[1].advance(1)
        for child in children:
            child.close()


def test_progress_manager_disables_child_bars():
    logger = logging.getLogger("progress-child-disabled-test")
    logger.setLevel(logging.INFO)
    with patch.object(sys.stderr, "isatty", return_value=True):
        manager = ProgressManager(
            total_steps=1,
            report_name="report",
            logger=logger,
            children_enabled=False,
        )
        children = manager.create_children(count=2, total=4, label="worker")
        assert children == []


def test_parallel_map_advances_main_when_enabled():
    progress = RecordingProgress()

    result = parallel_map(
        lambda value: value * 2,
        [1, 2, 3],
        max_workers=2,
        progress_manager=progress,
        advance_main=True,
    )

    assert result == [2, 4, 6]
    assert progress.current == 3


def test_parallel_map_does_not_advance_main_by_default():
    progress = RecordingProgress()

    result = parallel_map(
        lambda value: value * 2,
        [1, 2, 3],
        max_workers=2,
        progress_manager=progress,
    )

    assert result == [2, 4, 6]
    assert progress.current == 0
