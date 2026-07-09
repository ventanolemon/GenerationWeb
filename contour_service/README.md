# contour_service — сервис LLM-петли S0–S6

Реализация проектного пакета контура:
`Generator/docs/closed_loop_contract.md` (протокол, бюджеты V=3/R=2,
инварианты), `Generator/docs/critic_taxonomy.md` (29 кодов, probe, I/O
критика), `docs/architecture/contour_integration.md` (джобы, статусы,
персист), `docs/architecture/system_topology.md` (границы, очередь,
реестр провайдеров).

## Запуск

```bash
# из корня монорепо
uvicorn contour_service.main:app --host 127.0.0.1 --port 8001
# воркеры отдельными процессами (встроенный отключается env'ом):
CONTOUR_WORKER_DISABLED=1 uvicorn contour_service.main:app ... &
python -m contour_service.worker
```

Окружение: `CONTOUR_PROVIDER=mock|anthropic` (+ `ANTHROPIC_API_KEY`,
`CONTOUR_LLM_MODEL`), `CONTOUR_PG_DSN` (пусто → SQLite-файл монорепо),
`CONTOUR_DB_PATH`, `CONTOUR_V_BUDGET`/`CONTOUR_R_BUDGET`,
`CONTOUR_PROBE_SEEDS`, `CONTOUR_TOKEN_BUDGET`, `CONTOUR_JOB_TIMEOUT_S`.

## Карта модулей

| Модуль | Стадия петли | Что делает |
|---|---|---|
| `grounding.py` | S0 | компактный каталог из NodeRegistry (импорт `core.graph_api`) + few-shot retrieval (graph_examples + принятый корпус) |
| `prompts.py` | S1/S5 | тексты промптов генератора и критика; формат repair-сообщения §2 контракта; таксономия 29 кодов |
| `loop.py` | S1–S5 | оркестратор: бюджеты V/R, repair-петля, нормализация вердикта критика (evidence-правило, свёртка) |
| `core/graph_probe.py` | S3–S4 | (общий модуль ядра) probe на K seed + ПОЛНАЯ SYM-колонка таксономии: B4 B5 D2 E4 F1 F2 F3 F4 |
| `providers/` | S1/S5 | реестр task_type→провайдер; `MockProvider` (тесты/dev), `AnthropicProvider` (боевой) |
| `queue.py` | — | job-очередь: `PostgresJobQueue` (FOR UPDATE SKIP LOCKED) и `SqliteJobQueue` (dev/тесты) |
| `corpus.py` + `graph_hash.py` | персист | corpus_records по training_example_schema; канонический хэш (топосорт → переименование → sha256), дедуп UNIQUE-индексом |
| `routers/jobs.py` | S6 | POST/GET джоб, approve (партиция constracted=4 + корпус), reject |
| `worker.py` | — | claim → петля → персист; отказ провайдера = failed без расхода V |

## Тесты

```bash
python -m unittest discover contour_service/tests -t .
```

33 теста, headless, без сети. Покрывают: полный цикл queued→…→awaiting_human→
approved с проверкой партиции и корпуса; repair-раунд seed-rep-001 (дословный
текст `GraphValidationError` в repair-сообщении, полный предыдущий граф);
исчерпание бюджетов V/R → эскалация; инвариант «критик не видит невалидный
граф»; graph_hash-дедуп (переименование id не меняет хэш); очередь (claim/
reclaim/владение). Интеграционные (живой Postgres / живой Anthropic) скипаются
без `CONTOUR_PG_DSN` / `ANTHROPIC_API_KEY` — pytest в окружении нет, эквивалент
`@pytest.mark.integration` — `unittest.skipUnless` по env.
