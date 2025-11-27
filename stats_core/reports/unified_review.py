"""
Unified review statistics report (migrated from legacy unified_review_stat.py).
"""

from __future__ import annotations

import logging
from datetime import datetime
from configparser import ConfigParser
from pathlib import Path

from ..export import excel as excel_export, csv_export, word as word_export
from . import registry
from .unified_review_utils import HEADERS, parse_links, process_link

logger = logging.getLogger(__name__)


@registry.register
class UnifiedReviewReport:
    name = "unified_review"

    def run(
        self,
        dataset: dict,
        config: ConfigParser,
        output_formats: list[str],
        extra_params: dict | None = None,
    ) -> None:
        from ..config import create_cache_manager
        from . import unified_review_utils

        # Initialize cache manager
        cache_manager = create_cache_manager(config)
        unified_review_utils.set_cache_manager(cache_manager)

        extra_params = extra_params or {}
        links_file = extra_params.get("links_file") or _get_reporting_value(config, "links_file", "input.txt")
        links_file = links_file.strip() if links_file else links_file
        output_dir = extra_params.get("output_dir") or _get_reporting_value(config, "output_dir", "reports")
        output_base = Path(output_dir)
        output_base.mkdir(parents=True, exist_ok=True)
        output_name = extra_params.get("output", "review_summary")

        if not links_file:
            logger.warning("Links file is not configured. Set [reporting] links_file or pass --links-file.")
            return

        rows = self._rows_from_links(
            links_file=links_file,
            config=config,
            start_str=extra_params.get("start"),
            end_str=extra_params.get("end"),
        )

        # Save cache after processing
        cache_manager.save()

        if not rows:
            logger.warning("No review data collected, skipping export.")
            return

        if "excel" in output_formats:
            excel_export.export_sheet(output_base / f"{output_name}.xlsx", "Review Summary", HEADERS, rows)
        if "csv" in output_formats:
            csv_export.export_csv(output_base / f"{output_name}.csv", HEADERS, rows)
        if "word" in output_formats:
            word_template = extra_params.get("word_template") or _get_reporting_value(
                config, "review_word_template", ""
            )
            template_path = Path(word_template) if word_template else None
            if template_path and not template_path.exists():
                logger.warning("Word template %s not found. Using default layout.", template_path)
                template_path = None
            sections = [
                {
                    "title": extra_params.get("word_title", "Review Summary"),
                    "headers": HEADERS,
                    "rows": rows,
                    "font_name": extra_params.get("word_font", "Calibri (Body)"),
                    "font_size": int(extra_params.get("word_font_size", 8)),
                    "table_style": extra_params.get("word_table_style", "Table Grid"),
                }
            ]
            word_export.export_report(output_base / f"{output_name}.docx", sections, template=template_path)

    # Helpers -----------------------------------------------------------------

    def _rows_from_links(
        self,
        links_file: str,
        config: ConfigParser,
        start_str: str | None,
        end_str: str | None,
    ) -> list[list[str]]:
        try:
            links = parse_links(links_file)
        except FileNotFoundError:
            logger.warning("Links file %s not found.", links_file)
            return []

        logger.info("Processing %s links from %s", len(links), links_file)
        start_dt = self._parse_cli_dt(start_str)
        end_dt = self._parse_cli_dt(end_str)

        rows: list[list[str]] = []
        for link in links:
            row = process_link(link, config)
            if not row:
                logger.warning("Failed to process %s", link)
                continue
            if self._within_range(self._row_timestamp(row), start_dt, end_dt):
                rows.append(row)
        return rows

    @staticmethod
    def _parse_cli_dt(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            logger.warning("Неверный формат даты %s. Ожидалось YYYY-MM-DD.", value)
            return None

    @staticmethod
    def _row_timestamp(row: list[str]) -> datetime | None:
        for idx in (6, 5):  # merged_at first, fallback to created_at
            candidate = row[idx] if idx < len(row) else ""
            if not candidate:
                continue
            normalized = candidate.strip()
            if normalized.endswith("Z"):
                normalized = normalized[:-1] + "+00:00"
            try:
                return datetime.fromisoformat(normalized)
            except ValueError:
                continue
        return None

    @staticmethod
    def _within_range(
        value: datetime | None,
        start: datetime | None,
        end: datetime | None,
    ) -> bool:
        if not start and not end:
            return True
        if not value:
            return False
        if start and value < start:
            return False
        if end and value > end:
            return False
        return True


def _get_reporting_value(config: ConfigParser, key: str, fallback: str | None = None) -> str | None:
    if config.has_section("reporting"):
        return config["reporting"].get(key, fallback)
    return fallback

