# Feature Design Specification: AI Comments Quality and Language Fixes

## 1) Summary
Проблема: AI_Comments часто заполняется "Недостаточно данных", язык не соответствует требованию,
а ссылки типа "results: <url>" не превращаются в полезный прогресс.
Цель: улучшить промпт и пост-обработку AI_Comments, чтобы:
- язык был английский,
- ссылки и маркеры результатов давали осмысленную сводку,
- уменьшилось количество "Insufficient data".
Не цели: менять источники данных, добавлять новые зависимости, менять структуру отчётов.

## 2) Scope Boundaries
In scope:
- Обновление промпта AI для Comments_Period.
- Пост-обработка AI результата (нормализация, извлечение signal из "results:" и ссылок).
- Обновление дефолтного текста при отсутствии данных.

Out of scope:
- Новые AI провайдеры или зависимости.
- Изменение структуры отчёта или формата колонок.

## 3) Assumptions + Constraints
- Используется существующая AI-инфраструктура (Ollama/WebUI).
- Отчёт: `jira_comprehensive` и лист `Comments_Period`.
- Без новых зависимостей.

## 4) Architecture
Компоненты:
- `stats_core/reports/jira_comprehensive.py`
  - `_build_comment_summary_prompt` — обновить для английского и извлечения результатов.
  - `_format_ai_comment_summary` — улучшить fallback и "results:" обработку.

Data flow:
Comments_In_Period -> AI prompt -> JSON -> normalization -> AI_Comments.

## 5) Interfaces / Contracts
AI output format (unchanged):
```
{"t1": {"done":"...", "planned":"...", "risks":"...", "dependencies":"...", "notes":"..."}}
```
Требования:
- Язык: English.
- Если в комментариях есть "results:" или "result:", то это должно появиться в done/notes.
- Ссылки удаляются, но смысл сохраняется (например: "Results provided (link removed)").
- "Insufficient data" использовать только если реально нет полезного текста.

## 6) Data Model Changes
Нет.

## 7) Edge Cases + Failure Modes
- Только ссылка без описания -> “Results provided (link removed)” вместо “Insufficient data”.
- Несколько результатов -> краткий список без ссылок.
- В комментариях только мета/приветствия -> Insufficient data.

## 8) Security Requirements
- Не логировать полный текст комментариев.
- Не выводить ссылки в AI_Comments.

## 9) Performance Requirements
- Минимальные изменения: только пост-обработка строк.

## 10) Observability
- Логи только о количестве AI items и fallback count (без текста).

## 11) Test Plan
- Unit test: results link -> “Results provided”.
- Unit test: english output is enforced in prompt.
- Unit test: no data -> Insufficient data.
- `python -m pytest`.

## 12) Rollout Plan + Rollback Plan
Rollout:
- Обновить промпт и post-processing.

Rollback:
- Откатить изменения в `jira_comprehensive.py`.

## 13) Acceptance Criteria
- AI_Comments на английском.
- “results:” и ссылки дают содержательный вывод, не “Insufficient data”.
- Тесты проходят.

REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"
APPROVED:v1 (2026-02-26)
