from __future__ import annotations

import logging
from unittest.mock import patch

import sys
from stats_core.utils.progress import ProgressManager, TqdmLoggingHandler


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
