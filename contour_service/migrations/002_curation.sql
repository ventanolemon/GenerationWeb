-- Курация корпуса обучающих примеров (training_plan.md §1: перед QLoRA-SFT
-- сырой корпус нужно отсмотреть и разметить — «золотые» эталоны в приоритет
-- выборки, мусор исключить).
--
-- Курация — МУТАБЕЛЬНЫЙ оверлей над append-only corpus_records: держим её
-- отдельной таблицей 1:1 по record_id, а не колонками в corpus_records.
-- Причины: (1) corpus_records концептуально неизменяемы (это обучающие
-- данные с провенансом); (2) CREATE TABLE IF NOT EXISTS идемпотентен и в
-- SQLite, и в Postgres, тогда как ALTER TABLE ADD COLUMN в SQLite не умеет
-- IF NOT EXISTS и ломал бы повторный прогон миграций.
--
-- Записи без строки здесь трактуются как curation='auto' (не размечено).

CREATE TABLE IF NOT EXISTS corpus_curation (
    record_id  TEXT PRIMARY KEY REFERENCES corpus_records(id),
    curation   TEXT NOT NULL DEFAULT 'auto'
               CHECK (curation IN ('auto', 'gold', 'excluded')),
    comment    TEXT NOT NULL DEFAULT '',
    curated_by TEXT,                           -- логин куратора (admin)
    curated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_curation_state ON corpus_curation (curation);
