"""
Centralised configuration utilities.

The existing scripts relied on ad-hoc parsing of ``config.ini`` in each file.
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
from configparser import ConfigParser
from typing import Iterable, Mapping, MutableMapping, Any

DEFAULT_CONFIG_FILE = pathlib.Path("config.ini")
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
        path: Path to the configuration file.  Defaults to ``config.ini`` in
              the current working directory.
    """
    cfg_path = pathlib.Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"Config file '{cfg_path}' not found. "
            f"Run `python stats_main.py setup` to generate one."
        )

    config = ConfigParser()
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
        print("Токены не были обновлены. Обновите config.ini вручную при необходимости.")


def create_cache_manager(config: ConfigParser):
    """
    Create a CacheManager instance from configuration.

    Returns:
        CacheManager instance configured from [cache] section
    """
    from .cache import CacheManager

    if config.has_section("cache"):
        cache_section = config["cache"]
        cache_file = cache_section.get("file", "cache.json")
        enabled = cache_section.getboolean("enabled", True)
        ttl_days = cache_section.getint("ttl_days", 0)
    else:
        cache_file = "cache.json"
        enabled = True
        ttl_days = 0

    return CacheManager(cache_file=cache_file, enabled=enabled, ttl_days=ttl_days)


