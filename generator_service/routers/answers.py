"""
POST /answers/preview — «что примут» для преподавателя.

Зачем отдельный маршрут, а не поле в ответе `/generate`
------------------------------------------------------
Замер на этом коде: `accepted_examples()` для числа и строки стоит 0.03 мс,
для набора слотов — 6 мс, а для выражения в мягком режиме — **200 мс**:
там на каждого кандидата работает `simplify`. Положить это в
`StaticTask.to_dict()` рядом с виджетами значило бы добавить пятую долю
секунды к КАЖДОЙ генерации символьного задания ради подсказки, которую
смотрят один раз при настройке.

Есть и вторая причина, важнее производительности. Список принимаемых
ответов — материал ПРЕПОДАВАТЕЛЯ. Он и так виден рядом с ответом, но
поле в общем ответе `/generate` уехало бы и туда, где ответа нет, —
например в сессию, которую проходит студент. Отдельный маршрут делает
границу видимой в самом API, а не подразумеваемой.

Зачем это вообще нужно (§5 плана)
---------------------------------
Без списка «эти ответы будут засчитаны» рядом с переключателем строгости
механизм выключают на второй день, потому что не доверяют. Инвариант
«предпросмотр не врёт» держится в `AnswerSpec.accepted_examples`: каждый
пример прогоняется через собственный `check()`.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from core.answers import AnswerSpec, CheckMode

router = APIRouter(prefix="/answers", tags=["answers"])


class PreviewRequest(BaseModel):
    spec: dict = Field(..., description="Спецификация ответа (AnswerSpec.to_dict)")
    mode: Optional[str] = Field(
        None,
        description=("Режим сравнения для предпросмотра. Пусто — режим самой "
                     "спецификации. Задаётся, чтобы показать разницу между "
                     "мягким и строгим ДО переключения тумблера."))


class PreviewResponse(BaseModel):
    mode: str
    examples: List[str]
    fields: List[dict]
    tolerance: str = ""


@router.post("/preview", response_model=PreviewResponse)
def preview_answer(body: PreviewRequest) -> PreviewResponse:
    """
    Показать, какие ответы будут засчитаны.

    Спецификация приходит в теле, а не берётся по partition_id: тумблер
    крутят над ещё не сохранённым заданием — в редакторе графа и в форме
    настройки, — и требовать сохранения ради предпросмотра значило бы
    сделать его бесполезным ровно там, где он нужен.
    """
    try:
        spec = AnswerSpec.from_dict(body.spec)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=400,
                            detail=f"Спецификация не разобрана: {exc}")

    mode: Optional[CheckMode] = None
    if body.mode is not None:
        try:
            mode = CheckMode(body.mode)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=(f"Неизвестный режим {body.mode!r}; допустимы "
                        f"{', '.join(m.value for m in CheckMode)}."))

    try:
        examples = spec.accepted_examples(mode=mode)
    except Exception as exc:                           # noqa: BLE001
        # Разбор выражения может упасть на чём угодно, что дал автор.
        # Пустой список честнее пятисотки: предпросмотр — подсказка, а не
        # операция, ради которой стоит ронять настройку задания.
        raise HTTPException(status_code=400,
                            detail=f"Не удалось собрать примеры: {exc}")

    tolerance = getattr(spec, "tolerance", None)
    return PreviewResponse(
        mode=spec.effective_mode(mode).value,
        examples=examples,
        fields=[f.to_dict() for f in spec.input_fields()],
        tolerance=tolerance.describe() if tolerance is not None else "",
    )
