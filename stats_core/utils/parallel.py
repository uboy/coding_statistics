from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def parallel_map(
    func: Callable[[T], R],
    items: Iterable[T],
    *,
    max_workers: int = 4,
) -> list[R]:
    items_list = list(items)
    if not items_list:
        return []
    if max_workers <= 1:
        return [func(item) for item in items_list]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(func, items_list))
