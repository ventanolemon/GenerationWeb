-- 001_contour: таблицы LLM-контура (rbac_and_data_model.md §4, §5).
--
-- DDL портируемый: исполняется на SQLite (dev/тесты) как есть; на Postgres
-- отличий два — TEXT id хранит uuid (в PG допустимо заменить на uuid),
-- rounds/record хранятся строкой JSON (в PG — jsonb, содержимое то же).
-- Идемпотентно (IF NOT EXISTS): раннер может применять при каждом старте.
--
-- Очередью служит сама таблица contour_jobs (system_topology.md §4):
-- воркер забирает queued-строку (в Postgres — FOR UPDATE SKIP LOCKED,
-- см. contour_service/queue.py), смена статуса и персист артефактов
-- раунда — одна транзакция.

CREATE TABLE IF NOT EXISTS contour_jobs (
    id           TEXT PRIMARY KEY,            -- uuid4
    created_by   INTEGER NOT NULL,            -- users.id автора (владелец)
    subject_id   INTEGER NOT NULL,            -- предмет будущей партиции
    description  TEXT    NOT NULL,            -- запрос пользователя (S1-вход)
    constraints  TEXT    NOT NULL DEFAULT '{}',  -- JSON {task_type,...}
    status       TEXT    NOT NULL DEFAULT 'queued',
        -- queued → generating → validating → critic → awaiting_human →
        -- approved | rejected | escalated | failed   (contour_integration §2)
    rounds       TEXT    NOT NULL DEFAULT '[]',  -- JSON: история S1..S5
    result_graph TEXT,                         -- JSON GraphSpec последней успешной попытки
    result_probe TEXT,                         -- JSON probe-отчёт (экран S6)
    critic       TEXT,                         -- JSON последний вердикт критика
    error        TEXT,                         -- причина failed/escalated/rejected
    locked_by    TEXT,                         -- id воркера, держащего джобу
    locked_at    TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_contour_jobs_claim
    ON contour_jobs (status, created_at);
CREATE INDEX IF NOT EXISTS idx_contour_jobs_owner
    ON contour_jobs (created_by, created_at);

CREATE TABLE IF NOT EXISTS corpus_records (
    id         TEXT PRIMARY KEY,               -- uuid4
    job_id     TEXT NOT NULL REFERENCES contour_jobs(id),
    kind       TEXT NOT NULL CHECK (kind IN ('generate', 'repair', 'escalation')),
    record     TEXT NOT NULL,                  -- JSON по training_example_schema.json
                                               -- (kind=escalation — сырой лог, не для обучения)
    graph_hash TEXT,                           -- канонический хэш (NULL у escalation)
    created_at TEXT NOT NULL
);

-- Дедуп корпуса — UNIQUE-чек при вставке, не пост-обработка
-- (contour_integration.md §3). Частичный индекс работает и в SQLite, и в PG.
CREATE UNIQUE INDEX IF NOT EXISTS uq_corpus_kind_hash
    ON corpus_records (kind, graph_hash) WHERE graph_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_corpus_job ON corpus_records (job_id);
