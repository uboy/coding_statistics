"""
Centralised configuration utilities.

The existing scripts relied on ad-hoc parsing of ``config`` in each file.
This module provides a consolidated loader with the following features:

* Single entry point ``load_config`` that returns a ``ConfigParser`` ready for
  consumption throughout the code base.
* Token onboarding helpers – if a token for a service is missing, the helper
  can print actionable instructions (and optionally persist the new token).
* Convenience accessors for common options (Jira URL, output paths, etc.).
"""

from __future__ import annotations

import os
import pathlib
import logging
import re
import urllib.parse
from configparser import ConfigParser
from typing import Iterable, Mapping, MutableMapping, Any

DEFAULT_CONFIG_FILE = pathlib.Path("configs/local/config.ini")
logger = logging.getLogger(__name__)
TOKEN_HINTS: Mapping[str, str] = {
    "gitee": (
        "Создайте personal access token в https://gitee.com/profile/personal_access_tokens "
        "c правами на чтение репозиториев и вставьте его в секцию [gitee] как token=..."
    ),
    "gitcode": (
        "Перейдите на https://gitcode.com/ настройки профиля → Access Tokens и создайте токен "
        "с правами read_repository.  Добавьте его в секцию [gitcode]."
    ),
    "github": (
        "На https://github.com/settings/tokens/new создайте Fine-grained PAT с доступом "
        "к нужным репозиториям и сохраните его в секции [github]."
    ),
    "gitlab": (
        "Откройте https://gitlab.com/-/profile/personal_access_tokens (или свой инстанс GitLab), "
        "создайте PAT с read_api и сохраните его в [gitlab]."
    ),
    "gerrit": (
        "Сгенерируйте HTTP credentials в Gerrit (Settings → HTTP Password) и пропишите "
        "username/password в секции [gerrit]."
    ),
    "jira": (
        "Если Jira настроена на token-based auth – создайте API token на https://id.atlassian.com/manage-profile/"
        "security/api-tokens и сохраните его как password в секции [jira]."
    ),
}


def load_config(path: pathlib.Path | str = DEFAULT_CONFIG_FILE) -> ConfigParser:
    """
    Load configuration from the given path.

    Args:
        path: Path to the configuration file.  Defaults to
              ``configs/local/config.ini`` in
              the current working directory.
    """
    cfg_path = pathlib.Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Config file '{cfg_path}' not found. "
            f"Run `python stats_main.py setup` to generate one."
        )

    config = ConfigParser(
        strict=False,
        interpolation=None,
        inline_comment_prefixes=("#", ";"),
    )
    with cfg_path.open("r", encoding="utf-8-sig") as fh:
        config.read_file(fh)
    return config


def ensure_tokens(config: ConfigParser, services: Iterable[str]) -> list[str]:
    """
    Ensure that all required services have tokens configured.

    If a token/credential is missing, the user sees a hint with instructions.
    """
    missing: list[str] = []
    for service in services:
        if service not in config:
            missing.append(service)
            continue

        section: MutableMapping[str, str] = config[service]
        token = section.get("token")
        username = section.get("username")
        password = section.get("password")

        if token:
            continue
        if username and password:
            continue
        missing.append(service)

    return missing


def save_token(config: ConfigParser, service: str, token: str, path: pathlib.Path | str = DEFAULT_CONFIG_FILE) -> None:
    """
    Persist a token for the given service.
    """
    if service not in config:
        config.add_section(service)
    config.set(service, "token", token)
    with pathlib.Path(path).open("w", encoding="utf-8") as fh:
        config.write(fh)


def interactive_token_setup(config: ConfigParser, services: Iterable[str], path: pathlib.Path | str = DEFAULT_CONFIG_FILE) -> None:
    """
    Prompt the user to supply missing tokens interactively.
    """
    cfg_path = pathlib.Path(path)
    changed = False
    missing = ensure_tokens(config, services)
    if not missing:
        print("Все необходимые токены уже настроены.")
        return

    print("Следующие сервисы требуют настройки токенов/учётных данных:")
    for service in missing:
        hint = TOKEN_HINTS.get(service, f"Добавьте учётные данные в секцию [{service}].")
        print(f"\n[{service}] {hint}")
        token = input(f"Введите token для {service} (или оставьте пустым, чтобы пропустить): ").strip()
        if token:
            if service not in config:
                config.add_section(service)
            config.set(service, "token", token)
            changed = True
        else:
            username = input(f"Введите username для {service} (или Enter, чтобы пропустить): ").strip()
            if username:
                password = input(f"Введите password/API token для {service}: ").strip()
                if service not in config:
                    config.add_section(service)
                config.set(service, "username", username)
                config.set(service, "password", password)
                changed = True
    if changed:
        with cfg_path.open("w", encoding="utf-8") as fh:
            config.write(fh)
        print(f"Файл конфигурации обновлён: {cfg_path}")
    else:
        print("Токены не были обновлены. Обновите configs/local/config.ini вручную при необходимости.")


def create_cache_manager(config: ConfigParser):
    """
    Create a CacheManager instance from configuration.

    Returns:
        CacheManager instance configured from [cache] section
    """
    from .cache import CacheManager
    from .pathing import resolve_cache_path

    if config.has_section("cache"):
        cache_section = config["cache"]
        cache_file = str(resolve_cache_path(cache_section.get("file")))
        enabled = cache_section.getboolean("enabled", True)
        ttl_days = cache_section.getint("ttl_days", 0)
    else:
        cache_file = str(resolve_cache_path(None))
        enabled = True
        ttl_days = 0

    return CacheManager(cache_file=cache_file, enabled=enabled, ttl_days=ttl_days)


def get_ssl_config(config: ConfigParser) -> dict[str, Any]:
    """
    Get SSL configuration from config file.
    
    Returns:
        Dict with 'verify', 'bundle_ca_path', 'check_hostname' keys
    """
    ssl_config = {
        "verify": True,
        "bundle_ca_path": None,
        "check_hostname": True,
    }
    
    if config.has_section("ssl"):
        ssl_section = config["ssl"]
        # Allow disabling SSL verification (not recommended but sometimes needed)
        verify_str = ssl_section.get("verify", "true")
        ssl_config["verify"] = verify_str.lower() not in ("false", "0", "no", "off")
        
        # Custom bundle-ca path
        bundle_ca = ssl_section.get("bundle_ca", raw=True) or ssl_section.get("bundle-ca", raw=True)
        if bundle_ca:
            if os.path.exists(bundle_ca) and os.path.isfile(bundle_ca):
                ssl_config["bundle_ca_path"] = os.path.abspath(bundle_ca)
            else:
                logger.warning("SSL bundle-ca file not found: %s", bundle_ca)
        else:
            # Default: check for bundle-ca in current directory
            if os.path.exists("bundle-ca") and os.path.isfile("bundle-ca"):
                ssl_config["bundle_ca_path"] = os.path.abspath("bundle-ca")
        
        # Check hostname setting
        check_hostname_str = ssl_section.get("check_hostname", "true")
        ssl_config["check_hostname"] = check_hostname_str.lower() not in ("false", "0", "no", "off")
    else:
        # Default: check for bundle-ca in current directory
        if os.path.exists("bundle-ca") and os.path.isfile("bundle-ca"):
            ssl_config["bundle_ca_path"] = os.path.abspath("bundle-ca")
    
    return ssl_config


def get_proxy_config(config: ConfigParser) -> dict[str, str | None] | None:
    """
    Get proxy configuration from config file or environment variables.
    
    Priority:
    1. [proxy] section in config file (http, https, no_proxy)
    2. Environment variables (HTTP_PROXY, HTTPS_PROXY, NO_PROXY)
    
    Returns:
        Dict with 'http', 'https', 'no_proxy' keys, or None if no proxy configured
    """
    proxies: dict[str, str | None] = {}

    def _first(*values: str | None) -> str | None:
        for value in values:
            if value is None:
                continue
            normalized = str(value).strip()
            if normalized:
                return normalized
        return None

    def _section(name: str):
        if config.has_section(name):
            return config[name]
        wanted = name.casefold()
        for existing in config.sections():
            if existing.casefold() == wanted:
                return config[existing]
        return None

    proxy_section = _section("proxy")
    global_section = _section("global")

    cidr_v4_pattern = re.compile(r"^\\d{1,3}(?:\\.\\d{1,3}){3}/\\d{1,2}$")
    cidr_v6_pattern = re.compile(r"^[0-9A-Fa-f:]+/\\d{1,3}$")

    def _normalize_no_proxy(value: str | None) -> str | None:
        if not value:
            return None
        parts: list[str] = []
        for raw_part in str(value).split(","):
            part = raw_part.strip()
            if not part:
                continue
            if (part.startswith('"') and part.endswith('"')) or (part.startswith("'") and part.endswith("'")):
                part = part[1:-1].strip()
            if part.startswith("*."):
                part = part[1:]
            if "://" in part:
                parsed = urllib.parse.urlparse(part)
                if parsed.hostname:
                    part = parsed.hostname
                    if parsed.port:
                        part = f"{part}:{parsed.port}"
            elif "/" in part and not (cidr_v4_pattern.match(part) or cidr_v6_pattern.match(part)):
                part = part.split("/", 1)[0].strip()
            if part:
                parts.append(part)
        normalized = ",".join(parts)
        return normalized or None

    # 1) [proxy] section (preferred)
    http_proxy = None
    https_proxy = None
    no_proxy = None
    if proxy_section is not None:
        http_proxy = _first(
            proxy_section.get("http", raw=True, fallback=None),
            proxy_section.get("http_proxy", raw=True, fallback=None),
            proxy_section.get("HTTP_PROXY", raw=True, fallback=None),
        )
        https_proxy = _first(
            proxy_section.get("https", raw=True, fallback=None),
            proxy_section.get("https_proxy", raw=True, fallback=None),
            proxy_section.get("HTTPS_PROXY", raw=True, fallback=None),
        )
        no_proxy = _first(
            proxy_section.get("no_proxy", raw=True, fallback=None),
            proxy_section.get("NO_PROXY", raw=True, fallback=None),
        )

    # 1.1) Backward-compatible: proxy keys in [global]
    if global_section is not None:
        http_proxy = http_proxy or _first(
            global_section.get("http", raw=True, fallback=None),
            global_section.get("http_proxy", raw=True, fallback=None),
            global_section.get("HTTP_PROXY", raw=True, fallback=None),
        )
        https_proxy = https_proxy or _first(
            global_section.get("https", raw=True, fallback=None),
            global_section.get("https_proxy", raw=True, fallback=None),
            global_section.get("HTTPS_PROXY", raw=True, fallback=None),
        )
        no_proxy = no_proxy or _first(
            global_section.get("no_proxy", raw=True, fallback=None),
            global_section.get("NO_PROXY", raw=True, fallback=None),
        )

    no_proxy = _normalize_no_proxy(no_proxy)

    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    if no_proxy:
        proxies["no_proxy"] = no_proxy

    # 2) Fallback to environment variables if not in config
    proxies["http"] = proxies.get("http") or os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    proxies["https"] = proxies.get("https") or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    proxies["no_proxy"] = proxies.get("no_proxy") or os.environ.get("NO_PROXY") or os.environ.get("no_proxy")

    # Return None if no proxy configured
    if not proxies.get("http") and not proxies.get("https"):
        return None

    # Remove None values
    return {k: v for k, v in proxies.items() if v}


