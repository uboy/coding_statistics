"""
CSV export helpers.
"""

from pathlib import Path
from typing import Iterable
import csv


def export_csv(output_path: Path, headers: Iterable[str], rows: Iterable[Iterable[str]]) -> None:
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        writer.writerows(rows)

