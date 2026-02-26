from __future__ import annotations

import logging
from unittest.mock import patch

from stats_core.utils.progress import ProgressManager, TqdmLoggingHandler


def test_tqdm_logging_handler_uses_tqdm_write():
    logger = logging.getLogger("tqdm-test")
    logger.setLevel(logging.INFO)
    handler = TqdmLoggingHandler()
    logger.addHandler(handler)
    try:
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
