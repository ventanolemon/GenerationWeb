"""
Допуск опечатки в словарном диктанте: свойство слова В СЛОВАРЕ.

Замер, из-за которого этот модуль появился
------------------------------------------
Мягкая проверка тренажёра принимала правку на расстоянии Левенштейна ≤ 1
(≤ 2 для длинных слов). На поставочных словарях (160 слов) это дало **17
пар, неразличимых проверкой**, и пары там не случайные:

    LAN  ← принимает MAN, WAN, WLAN
    AI   ← принимает AR
    DSL  ← принимает SDSL, SSL
    hardware ← принимает shareware

Все они есть в том же словаре как РАЗНЫЕ термины. Студент, написавший
«WAN» вместо «LAN», не опечатался — он не знает разницы, а проверка
засчитывала это как знание. Для словарного диктанта это не мелкая
неточность, а отказ проверять ровно то, ради чего диктант проводится.

Правило
-------
Допуск не может быть свойством одного слова. Он ограничен **окрестностью
слова в словаре**:

    порог = min(политика_по_длине, расстояние_до_ближайшего_соседа − 1)

Из этого следует главное свойство, и оно выполняется ПО ПОСТРОЕНИЮ, а не
подбором констант: **другое слово словаря не может быть принято как
опечатка**. Если сосед на расстоянии 1, допуска нет вовсе — и это верно:
в такой окрестности опечатка неотличима от другого термина, и принимать
её значит гадать за студента.

Цена измерена: из 128 слов, где проверялась опечатка-пропуск, принимаются
по-прежнему 121. Потерянные семь — ровно те, у которых сосед вплотную.

Почему в `core/`, а не в тренажёре
----------------------------------
Тот же довод, что у остальных понятий равенства (`boolean_text`,
`program_output`, `equation_text`): проверка ответа и генерация примеров
для предпросмотра обязаны понимать «то же самое» одинаково. Разложенное
по вызывающим правило живёт до первого нового вызывающего — а их уже
два, и они уже разошлись: тренажёр принимал «ct» за «cat», а слот
ответа — нет.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Optional


def levenshtein(a: str, b: str) -> int:
    """
    Расстояние Левенштейна: минимум односимвольных правок (вставка,
    удаление, замена), переводящих `a` в `b`.

    Классическая динамика на двух строках — O(|a|·|b|) по времени,
    O(|b|) по памяти.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(
                previous[j] + 1,          # удаление
                current[j - 1] + 1,       # вставка
                previous[j - 1] + (ca != cb),   # замена
            ))
        previous = current
    return previous[-1]


def length_budget(word: str) -> int:
    """
    Сколько правок допустимо по одной лишь длине слова.

    Одна правка на каждые четыре символа. Короче четырёх — правок нет
    вовсе: в слове из трёх букв опечатка неотличима от другого слова.
    Правило то же, что у `TextSpec._edit_budget`, и это не совпадение —
    расхождение двух политик и было половиной дефекта.
    """
    return max(0, len(word.strip()) // 4)


def nearest_distance(word: str, vocabulary: Iterable[str]) -> Optional[int]:
    """
    Расстояние до ближайшего ДРУГОГО слова словаря; None — соседей нет.

    Сравнение пропускается, если длины различаются больше, чем на
    интересующий нас предел: расстояние Левенштейна не меньше разницы
    длин, и считать его полностью незачем. На словаре в сотни слов это
    разница между «мгновенно» и «заметно».
    """
    target = word.strip().lower()
    best: Optional[int] = None
    limit = length_budget(target) + 1
    for other in vocabulary:
        candidate = str(other).strip().lower()
        if not candidate or candidate == target:
            continue
        if abs(len(candidate) - len(target)) > limit:
            continue
        distance = levenshtein(target, candidate)
        if best is None or distance < best:
            best = distance
            if best <= 1:
                break                     # ближе уже не будет
    return best


def budget(word: str, vocabulary: Iterable[str] | None = None) -> int:
    """
    Итоговый допуск для слова: политика по длине, ужатая окрестностью.

    Без словаря остаётся только политика по длине — это честный откат
    для случая, когда набор слов неизвестен (одиночный слот ответа), а не
    «разрешим побольше на всякий случай».
    """
    limit = length_budget(word)
    if vocabulary is None:
        return limit
    nearest = nearest_distance(word, vocabulary)
    if nearest is None:
        return limit
    return max(0, min(limit, nearest - 1))


def accepts(word: str, answer: str, vocabulary: Iterable[str] | None = None,
            ) -> bool:
    """Принять ли `answer` как `word` с точностью до опечатки."""
    target = word.strip().lower()
    given = answer.strip().lower()
    if target == given:
        return True
    allowed = budget(word, vocabulary)
    return allowed > 0 and levenshtein(given, target) <= allowed


def vocabulary_collisions(words: Iterable[str]) -> list[tuple[str, str, int]]:
    """
    Пары слов, которые проверка не различит. Пустой список — инвариант
    соблюдён.

    Нужна не для работы, а для ПРОВЕРКИ работы: главное свойство правила
    формулируется как «таких пар нет», и проверять его надо прогоном по
    настоящему словарю, а не рассуждением о константах.
    """
    vocabulary = [str(w).strip().lower() for w in words if str(w).strip()]
    found = []
    for word in vocabulary:
        allowed = budget(word, vocabulary)
        if allowed <= 0:
            continue
        for other in vocabulary:
            if other == word:
                continue
            distance = levenshtein(word, other)
            if 0 < distance <= allowed:
                found.append((word, other, distance))
    return found


def as_mapping_keys(words: Mapping[str, str] | Iterable[str]) -> list[str]:
    """Словарь `term → перевод` или просто список — привести к списку слов."""
    if isinstance(words, Mapping):
        return [str(k) for k in words]
    return [str(w) for w in words]
