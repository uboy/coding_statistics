from __future__ import annotations

from stats_core.utils.parallel import parallel_map


def test_parallel_map_preserves_order():
    items = [1, 2, 3, 4]
    result = parallel_map(lambda x: x * 2, items, max_workers=2)
    assert result == [2, 4, 6, 8]
