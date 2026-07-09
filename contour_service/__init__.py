"""
contour_service — сервис LLM-петли S0–S6 (docs/architecture/system_topology.md).

Владеет: job-очередью (Postgres/SQLite, FOR UPDATE SKIP LOCKED), реестром
нейропровайдеров, оркестратором петли (closed_loop_contract.md) и персистом
корпуса (corpus_records). Стадии S2–S4 — ИМПОРТ core/graph + core.graph_probe,
не сетевые вызовы.
"""
