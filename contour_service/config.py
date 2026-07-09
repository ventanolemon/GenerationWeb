"""
Конфигурация contour_service. Все значения переопределяются переменными
окружения; дефолты — из проектных документов:

  - бюджеты V=3 / R=2            — closed_loop_contract.md §3
  - K seed probe = 8 (релиз 32)  — critic_taxonomy.md §5
  - таймаут джобы 15 мин         — contour_integration.md §5
  - ретраи провайдера            — contour_integration.md §5 (недоступность
    LLM не жжёт бюджет V — это не ошибка графа)
"""

from __future__ import annotations
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


def _engine_commit() -> str:
    """Коммит движка (для provenance корпуса). Env → git → 'unknown'."""
    env = os.environ.get("ENGINE_COMMIT", "").strip()
    if env:
        return env
    try:
        root = Path(__file__).resolve().parent.parent
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


@dataclass
class ContourConfig:
    """Параметры петли и инфраструктуры одного процесса contour_service."""

    # Бюджеты петли (closed_loop_contract.md §3).
    v_budget: int = 3          # раунды сборки/исполнения (S2+S3+S4 суммарно)
    r_budget: int = 2          # revise-раунды критика

    # Probe (critic_taxonomy.md §5).
    probe_seeds: list[int] = field(default_factory=lambda: list(range(8)))

    # Few-shot заземления (closed_loop_contract.md S0: 2–4 примера).
    fewshot_count: int = 3

    # Отказы (contour_integration.md §5).
    provider_retries: int = 2          # ретраи вызова LLM до status=failed
    job_timeout_s: float = 15 * 60.0   # таймаут джобы целиком

    # Общий токен-бюджет на задание (closed_loop_contract.md §3);
    # 0 = не ограничен. Учитывается по usage, который вернул провайдер.
    token_budget: int = 0

    # БД: по умолчанию — та же SQLite, что у остального монорепо (approve
    # пишет партицию туда же); Postgres включается DSN'ом.
    db_path: str = ""
    pg_dsn: str = ""

    # Провайдеры: "mock" (тесты/dev без ключа) или "anthropic".
    provider_backend: str = "mock"

    engine_commit: str = field(default_factory=_engine_commit)

    @classmethod
    def from_env(cls) -> "ContourConfig":
        from const import DB_PATH
        cfg = cls()
        cfg.v_budget = int(os.environ.get("CONTOUR_V_BUDGET", cfg.v_budget))
        cfg.r_budget = int(os.environ.get("CONTOUR_R_BUDGET", cfg.r_budget))
        k = int(os.environ.get("CONTOUR_PROBE_SEEDS", len(cfg.probe_seeds)))
        cfg.probe_seeds = list(range(k))
        cfg.fewshot_count = int(os.environ.get("CONTOUR_FEWSHOT", cfg.fewshot_count))
        cfg.provider_retries = int(
            os.environ.get("CONTOUR_PROVIDER_RETRIES", cfg.provider_retries))
        cfg.job_timeout_s = float(
            os.environ.get("CONTOUR_JOB_TIMEOUT_S", cfg.job_timeout_s))
        cfg.token_budget = int(
            os.environ.get("CONTOUR_TOKEN_BUDGET", cfg.token_budget))
        cfg.db_path = os.environ.get("CONTOUR_DB_PATH", str(DB_PATH))
        cfg.pg_dsn = os.environ.get("CONTOUR_PG_DSN", "")
        default_backend = ("anthropic"
                           if os.environ.get("ANTHROPIC_API_KEY") else "mock")
        cfg.provider_backend = os.environ.get(
            "CONTOUR_PROVIDER", default_backend)
        return cfg
