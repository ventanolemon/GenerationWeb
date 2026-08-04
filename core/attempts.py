"""
Запись попытки: контракт режима, выраженный кодом.

План, §4: четыре режима прохождения — это четыре разных **контракта о
записи попытки**, а не четыре набора настроек. Отличие «тренировки без
статистики» от «тренировки со статистикой» не в значении параметра, а в
том, что в первом случае строки не появляется вовсе.

Здесь этот контракт исполняется в одном месте, чтобы «не писать попытку»
нельзя было забыть. Разложенное по вызывающим правило живёт до первого
нового вызывающего.

Про идемпотентность
-------------------
Ключ попытки считается ДЕТЕРМИНИРОВАННО из (сессия, номер вопроса), а не
случайно. Случайный uuid при повторной записи той же сессии дал бы вторую
строку про тот же ответ, и успеваемость поехала бы вверх на ровном месте.
Вставка идёт через INSERT OR IGNORE — так уже устроен синк.

Здесь только МОДЕЛЬ, без записи в БД
------------------------------------
Запись живёт на сервере (`core/repo/runtime.py`), потому что таблица
`attempts` серверная: у десктопа её нет, он отправляет попытки синком.
Держать здесь писатель SQL значило бы возить в десктопное ядро функцию,
которая обращается к несуществующей таблице, — и однажды кто-нибудь её
вызовет.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import List, Optional

from .scenarios import Scenario


ATTEMPT_COLUMNS = (
    "client_uuid", "user_id", "partition_id", "assignment_id", "payload",
    "correct", "device_id", "created_at",
    "session_mode", "check_mode", "adaptive", "attempts_used",
    "counts_toward_stats",
)


@dataclass(frozen=True)
class AttemptRecord:
    """Одна попытка — один ответ на один вопрос."""

    client_uuid: str
    user_id: str
    partition_id: int
    correct: Optional[bool]
    session_mode: str
    check_mode: str
    adaptive: bool
    attempts_used: int
    counts_toward_stats: bool = True
    assignment_id: Optional[int] = None
    device_id: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    payload: dict = field(default_factory=dict)

    def as_row(self) -> tuple:
        return (
            self.client_uuid,
            self.user_id,
            int(self.partition_id),
            self.assignment_id,
            json.dumps(self.payload, ensure_ascii=False),
            None if self.correct is None else int(bool(self.correct)),
            self.device_id,
            float(self.created_at),
            self.session_mode,
            self.check_mode,
            int(bool(self.adaptive)),
            int(self.attempts_used),
            int(bool(self.counts_toward_stats)),
        )


def attempt_uuid(session_id: str, question_index: int) -> str:
    """
    Детерминированный ключ попытки.

    Повторная запись той же сессии обязана попасть в ту же строку, иначе
    повтор запроса удвоит успеваемость. Хеш, а не «sid:index», чтобы длина
    ключа не зависела от длины идентификатора сессии.
    """
    raw = f"{session_id}#{question_index}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def attempts_from_session(
    session,
    scenario: Scenario,
    *,
    session_id: str,
    user_id: str,
    partition_id: int,
    assignment_id: Optional[int] = None,
    device_id: Optional[str] = None,
    now: Optional[float] = None,
) -> List[AttemptRecord]:
    """
    Собрать попытки по итогам сессии — или НЕ собрать, если режим не пишет.

    Пустой список это не «нечего записать», а исполненный контракт: в
    свободной тренировке попыток не существует, и вызывающему не нужно
    об этом помнить.

    Записываются только ЗАКРЫТЫЕ вопросы (`session.outcomes`). Незакрытый
    вопрос — это вопрос, на котором студент сейчас находится, и писать по
    нему результат не о чем.
    """
    contract = scenario.contract
    if not contract.records_attempts:
        return []

    stamp = time.time() if now is None else now
    records: List[AttemptRecord] = []
    for outcome in session.outcomes:
        records.append(AttemptRecord(
            client_uuid=attempt_uuid(session_id, outcome.index),
            user_id=user_id or "",
            partition_id=partition_id,
            correct=outcome.accepted,
            # Режим проверки берётся из ВЕРДИКТА, а не из сценария: если
            # вызывающий перекрыл режим на один ход, в попытке обязано
            # оказаться то, чем на самом деле проверяли (§5.1).
            check_mode=outcome.mode,
            session_mode=scenario.mode.value,
            adaptive=scenario.adaptive,
            attempts_used=outcome.attempts,
            counts_toward_stats=contract.counts_toward_stats,
            assignment_id=assignment_id,
            device_id=device_id,
            created_at=stamp,
            payload={
                "question_index": outcome.index,
                "reason": outcome.reason,
            },
        ))
    return records


__all__ = [
    "AttemptRecord", "ATTEMPT_COLUMNS", "attempt_uuid",
    "attempts_from_session",
]
