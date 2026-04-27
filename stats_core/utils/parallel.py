from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import math
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def parallel_map(
    func: Callable[[T], R],
    items: Iterable[T],
    *,
    max_workers: int = 4,
    progress_manager=None,
    child_label: str = "worker",
    advance_main: bool = False,
) -> list[R]:
    items_list = list(items)
    if not items_list:
        return []
    if max_workers <= 1:
        results = []
        for item in items_list:
            result = func(item)
            if advance_main and progress_manager is not None:
                progress_manager.advance(1)
            results.append(result)
        return results
    child_bars = []
    bar_map: dict[str, int] = {}
    bar_lock = threading.Lock()
    if progress_manager is not None:
        per_total = math.ceil(len(items_list) / max_workers)
        child_bars = progress_manager.create_children(count=max_workers, total=per_total, label=child_label)

    def _wrap(item: T) -> R:
        result = func(item)
        if advance_main and progress_manager is not None:
            progress_manager.advance(1)
        if child_bars:
            thread_name = threading.current_thread().name
            with bar_lock:
                idx = bar_map.get(thread_name)
                if idx is None:
                    idx = len(bar_map) % len(child_bars)
                    bar_map[thread_name] = idx
            child_bars[idx].advance(1)
        return result

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            return list(executor.map(_wrap, items_list))
    finally:
        for bar in child_bars:
            bar.close()
