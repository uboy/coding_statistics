"""
Unified review statistics report (migrated from legacy unified_review_stat.py).
"""

from __future__ import annotations

import atexit
import logging
import signal
import sys
from datetime import datetime, timezone
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
        from ..config import create_cache_manager, get_proxy_config, get_ssl_config
        from . import unified_review_utils

        # Initialize cache manager
        cache_manager = create_cache_manager(config)
        unified_review_utils.set_cache_manager(cache_manager)
        
        # Get SSL configuration
        ssl_config = get_ssl_config(config)
        unified_review_utils.set_ssl_config(ssl_config)
        
        # Register cache save on exit (for Ctrl+C, errors, normal exit)
        def save_cache_on_exit():
            try:
                cache_manager.save()
                cache_stats = cache_manager.get_stats()
                logger.info("Cache saved on exit: %s links, %s API responses", 
                           cache_stats.get("link_entries", 0),
                           cache_stats.get("api_entries", 0))
            except Exception as e:
                logger.error("Failed to save cache on exit: %s", e)
        
        # Register for normal exit
        atexit.register(save_cache_on_exit)
        
        # Register for signal handlers (Ctrl+C, SIGTERM)
        def signal_handler(signum, frame):
            logger.info("Received signal %s, saving cache...", signum)
            save_cache_on_exit()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, signal_handler)
        
        # Get proxy configuration
        proxy_config = get_proxy_config(config)
        unified_review_utils.set_proxy_config(proxy_config)
        
        # Log cache status
        if cache_manager.enabled:
            cache_stats = cache_manager.get_stats()
            logger.info("Cache enabled: file=%s, existing entries: %s links, %s API responses",
                       cache_manager.cache_file,
                       cache_stats.get("link_entries", 0),
                       cache_stats.get("api_entries", 0))
        else:
            logger.warning("Cache is disabled")
        
        # Log proxy status
        if proxy_config:
            logger.info("Proxy configured: %s", {k: v if "password" not in str(v).lower() else "***" for k, v in proxy_config.items() if k != "no_proxy"})
        else:
            logger.debug("No proxy configuration found")

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

        try:
            rows = self._rows_from_links(
                links_file=links_file,
                config=config,
                start_str=extra_params.get("start"),
                end_str=extra_params.get("end"),
            )
        finally:
            # Always save cache, even if processing fails
            cache_manager.save()
            cache_stats = cache_manager.get_stats()
            logger.info("Cache saved: %s link entries, %s API entries", 
                       cache_stats.get("link_entries", 0),
                       cache_stats.get("api_entries", 0))

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
            dt = datetime.fromisoformat(value)
            # Normalise to UTC-aware for consistent comparison with API timestamps
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            else:
                dt = dt.astimezone(timezone.utc)
            return dt
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
        # Normalise all datetimes to naive UTC to avoid offset-aware/naive comparison issues
        def _norm(dt: datetime | None) -> datetime | None:
            if not dt:
                return None
            if dt.tzinfo is not None:
                return dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt

        value = _norm(value)
        start = _norm(start)
        end = _norm(end)

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

