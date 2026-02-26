# Feature Design Specification: Report Progress Logging, AI Retries, Parallelization

## 1) Summary
Проблема: при запуске отчётов нет явного понимания прогресса, логирование мешает отображению,
AI-запросы при таймаутах не повторяются, а тяжёлые операции не параллелятся.
Цель: добавить единый прогресс-бар для всех отчётов, структурированные логи по шагам,
повтор AI-запросов при таймаутах, и параллельное выполнение тяжёлых задач.
Не цели: менять бизнес-логику отчётов, добавлять новые зависимости, менять форматы отчётов.

## 2) Scope Boundaries
In scope:
- Прогресс-бар для любого отчёта (`stats_main.py run --report ...`) с корректным выводом при логах.
- Логи: время старта, имя отчёта, шаг начался/завершился.
- Повторы AI-запросов при таймауте: 3 попытки с паузой.
- Параллелизация тяжёлых операций (например, AI-батчи, независимые расчёты).

Out of scope:
- Новый UI, веб-интерфейс, графические прогресс-виджеты.
- Новые зависимости.
- Параллелизация операций, которые не являются независимыми или потокобезопасными.

## 3) Assumptions + Constraints
- Проект Python CLI, отчёты реализованы в `stats_core/reports/*`.
- В `requirements.txt` уже есть `tqdm` (можно использовать без новых зависимостей).
- Логирование настраивается через `stats_core/cli.py`.
- Нельзя ломать совместимость CLI.

## 4) Architecture
Компоненты:
- `stats_core/utils/progress.py`:
  - `ProgressManager` с `tqdm` баром
  - `ProgressStep` (контекстный менеджер) для шагов
  - логгер-хэндлер, который пишет через `tqdm.write`
- `stats_core/utils/ai_retry.py`:
  - `retry_ai_call(fn, retries=3, backoff_seconds=[1,2,3])`
  - обработка `requests` таймаутов
- Изменения в `stats_core/cli.py`:
  - создание `ProgressManager` в `cmd_run`
  - передача менеджера в отчёт через `extra_params` (например, `progress_manager`)
- Изменения в отчётах:
  - Явная разметка шагов (fetch data / compute / export)
  - Использование `ProgressManager.step("...")`
- Параллельное выполнение:
  - `stats_core/utils/parallel.py`: `parallel_map` на `ThreadPoolExecutor`
  - Используется для AI-запросов и тяжёлых независимых операций

Data flow:
CLI -> ProgressManager -> Report.run
Report.run -> Steps -> AI calls (with retry + optional parallel)

## 5) Interfaces / Contracts
### ProgressManager API
- `ProgressManager(total_steps: int, report_name: str)`
- `step(name: str)` -> context manager
- `advance(n: int = 1)`
- `close()`

### Logging integration
- Новый logging handler: `TqdmLoggingHandler` использует `tqdm.write`,
  чтобы не ломать прогресс-бар.

### AI retry
- Все AI-запросы должны идти через `retry_ai_call`.
- Retry только на `requests.Timeout` и `requests.exceptions.ReadTimeout/ConnectTimeout`.
- Между попытками пауза (например 1s, 2s, 3s).

### Parallelization
- `parallel_map(func, items, max_workers)`
- По умолчанию `max_workers = 4`, переопределяется через `--params parallel_workers=...`
- Использовать только для независимых задач (AI батчи, независимые расчёты).

## 6) Data Model Changes
Нет.

## 7) Edge Cases + Failure Modes
- Запуск без TTY: `tqdm` должен корректно работать в обычном stdout.
- Исключение внутри шага: шаг логируется как "failed".
- Параллельные задачи могут завершиться с ошибками → агрегировать и логировать.
- AI ретраи не должны запускаться бесконечно.

## 8) Security Requirements
- Логи не должны печатать секреты.
- AI-запросы не должны логировать полный текст комментариев.
- Никаких новых зависимостей.

## 9) Performance Requirements
- Прогресс-бар не должен заметно замедлять отчёт.
- Параллельность ограничить разумным числом потоков (4–8).

## 10) Observability
- Логировать:
  - старт отчёта (время, имя отчёта)
  - начало/конец каждого шага
  - количество шагов/процент выполнения
  - количество retry для AI (только count, без тела)

## 11) Test Plan
- Unit-тест ProgressManager (бар не ломается при логах — проверка через mock).
- Unit-тест retry AI: 2 таймаута, успех на 3-й.
- Unit-тест parallel_map: корректный сбор результатов.
- Команда: `pytest tests`.

## 12) Rollout Plan + Rollback Plan
Rollout:
- Внедрить ProgressManager, AI retry, parallel_map.
- Подключить в CLI и основные отчёты.

Rollback:
- Откат изменений в `stats_core/utils/*` и использования ProgressManager/parallel_map.

## 13) Acceptance Criteria
- Любой отчёт показывает прогресс-бар от 0 до 100% без порчи логов.
- Логи содержат: старт отчёта, шаги start/end.
- AI вызовы при timeout повторяются до 3 раз с паузами.
- Тяжёлые задачи выполняются параллельно (AI батчи как минимум).
- Все тесты проходят.

REVIEW REQUIRED — Reply "APPROVED:v1" or "CHANGES:<bullets>"
APPROVED:v1 (2026-02-26)
