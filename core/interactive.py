"""
Общая интерактивная сессия: «спроси → проверь → покажи», написанная один раз.

План, §1: пока ответ хранился как список блоков вёрстки, сверить с ним ввод
было нельзя, и каждый интерактивный модуль писал собственный цикл. Так
появился `WordsSession` на 252 строки, из которых на саму тренировку слов
приходится меньшая часть, а остальное — общий каркас «спросить, принять
ответ, дать обратную связь, перейти к следующему».

Теперь ответ — типизированные данные (`core.answers`), и каркас становится
общим. Генератору больше не нужен свой подкласс `InteractiveTask`: он
прикрепляет к заданию спецификацию ответа, а сессию собирает эта машинка.

Что это НЕ делает
-----------------
Это не «интерактив включается сам по себе». Генератор всё равно правится —
он должен объявить, что считается верным ответом. Но правка это одно поле,
а не новый класс с собственным циклом, и «сделать готовое задание
интерактивным» перестаёт быть переписыванием.

Количество попыток и то, засчитывается ли прохождение, здесь заданы
минимально (одна попытка). По плану (§4) это свойство **сценария выдачи**,
а не задания: одно и то же задание в тренировке и в зачёте живёт
по-разному. Сценарий появится на этапе 3 и станет источником этих
значений; поле здесь оставлено, чтобы этап 3 менял вызывающего, а не
переписывал сессию.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

from .answers import AnswerSpec, CheckMode, Verdict
from .scenarios import Scenario
from .blocks import TextBlock, blocks_from_dicts
from .content import Block
from .task import TurnResult
from .task import InteractiveTask
from .widgets import resolve_widget


@dataclass
class Question:
    """
    Один вопрос сессии: что показать и что считать верным.

    `widget` — предпочтительный способ ввода. Пусто значит «пусть решает
    платформа»: реестр отдаст первый совместимый. Несовместимое имя — не
    молчаливая подмена, а ошибка (см. `widgets.resolve`), потому что
    иначе студент увидит не тот способ ввода, а причина будет не видна.
    """

    statement: List[Block]
    spec: AnswerSpec
    widget: str = ""

    options_count: int = 0
    """
    Сколько вариантов показать, если вопрос задаётся тестом. 0 — не тест.

    Число вариантов — свойство ПОКАЗА, а не ответа, поэтому живёт здесь,
    рядом с `widget`, а не в спецификации: один и тот же ответ бывает и
    полем ввода, и выбором из четырёх, и это решает тот, кто выдаёт
    задание, а не тот, кто его придумал.
    """

    def widget_name(self) -> str:
        """
        Чем рисовать ввод.

        Явно названный виджет главнее всего. Иначе: вопрос с вариантами —
        это выбор, и выводить это из `options_count` надо здесь, а не в
        каждом вызывающем, иначе одни начнут показывать варианты полем
        ввода, а другие полем ввода варианты.

        Если выбор со спецификацией несовместим (набор слотов тестом не
        задаётся), падать незачем — остаётся обычное умолчание реестра.
        """
        if not self.widget and self.options_count:
            from .widgets import registry
            choice = registry.get("choice_one")
            if choice is not None and choice.serves(self.spec):
                return choice.name
        chosen = resolve_widget(self.spec, self.widget)
        return chosen.name if chosen is not None else ""

    def options(self) -> List[str]:
        """
        Варианты теста или пусто.

        Пусто бывает и когда вопрос не тест, и когда честный тест собрать
        не из чего — дистракторов не нашлось. Второе не ошибка: лучше
        поле ввода, чем тест, в котором верный ответ виден методом
        исключения.
        """
        if not self.options_count:
            return []
        return self.spec.options(self.options_count)

    def to_dict(self) -> dict:
        out = {
            "statement": [b.to_dict() for b in self.statement],
            "spec": self.spec.to_dict(),
        }
        if self.widget:
            out["widget"] = self.widget
        if self.options_count:
            out["options_count"] = self.options_count
        return out

    @classmethod
    def from_dict(cls, data: dict) -> "Question":
        return cls(
            statement=blocks_from_dicts(data.get("statement")),
            spec=AnswerSpec.from_dict(data["spec"]),
            widget=data.get("widget", ""),
            options_count=int(data.get("options_count", 0) or 0),
        )


@dataclass
class Outcome:
    """Чем кончился вопрос. То, что этап 3 положит в попытку."""

    index: int
    accepted: bool
    attempts: int
    mode: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "accepted": self.accepted,
            "attempts": self.attempts,
            "mode": self.mode,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Outcome":
        return cls(
            index=int(data["index"]),
            accepted=bool(data["accepted"]),
            attempts=int(data.get("attempts", 1)),
            mode=str(data.get("mode", "")),
            reason=str(data.get("reason", "")),
        )


class SpecSession(InteractiveTask):
    """
    Сессия над последовательностью вопросов со спецификациями ответа.

    Один вопрос — частный случай последовательности из одного, поэтому
    отдельной «сессии одного задания» нет.
    """

    def __init__(
        self,
        questions: Sequence[Question],
        *,
        scenario: Optional["Scenario"] = None,
        mode: Optional[CheckMode] = None,
        max_attempts: int = 1,
        reveal_answer: bool = True,
        meta: Optional[dict] = None,
    ):
        self._questions: List[Question] = list(questions)
        self._scenario = scenario
        # Сценарий, если он есть, — источник этих значений (§4): лимиты и
        # «засчитывается ли» принадлежат ПРОХОЖДЕНИЮ, а не заданию.
        # Россыпь параметров осталась для вызывающих, которым сценарий не
        # нужен: тесты ядра и разовая проверка задания автором.
        if scenario is not None:
            mode = scenario.check_mode
            max_attempts = scenario.max_attempts
            reveal_answer = scenario.reveal_answer
        self._mode = mode
        self._max_attempts = max(1, int(max_attempts))
        self._reveal_answer = bool(reveal_answer)
        self.meta = dict(meta or {})

        self._index = 0
        self._attempts = 0
        self._outcomes: List[Outcome] = []

    # ---------- Чтение состояния ----------

    @property
    def questions(self) -> List[Question]:
        return list(self._questions)

    @property
    def scenario(self) -> Optional["Scenario"]:
        """
        Сценарий прохождения — источник контракта о записи попытки.

        None значит, что сессию открыли без сценария: так делают тесты и
        разовая проверка задания автором. Записывать попытки в этом случае
        не по чему, и это не умолчание, а отсутствие контракта.
        """
        return self._scenario

    @property
    def outcomes(self) -> List[Outcome]:
        """Итоги закрытых вопросов — источник для записи попытки (этап 3)."""
        return list(self._outcomes)

    @property
    def score(self) -> tuple:
        """(верных, всего) — по закрытым вопросам."""
        return (sum(1 for o in self._outcomes if o.accepted), len(self._questions))

    def current(self) -> Optional[Question]:
        if self._index >= len(self._questions):
            return None
        return self._questions[self._index]

    def is_finished(self) -> bool:
        return self._index >= len(self._questions)

    # ---------- Цикл ----------

    def initial_prompt(self) -> List[Block]:
        question = self.current()
        if question is None:
            return [TextBlock("Вопросов нет.")]
        return list(question.statement)

    def submit(self, user_input: str) -> TurnResult:
        question = self.current()
        if question is None:
            return TurnResult(False, [TextBlock("Сессия уже завершена.")], None)
        return self._turn(question,
                          question.spec.check(user_input, mode=self._mode))

    def submit_values(self, values: Dict[str, str]) -> TurnResult:
        """
        Ход виджета, у которого поля раздельные.

        Без этого пути многополевой ответ пришлось бы склеивать в строку
        «a=1; b=2» на клиенте, и значение с точкой с запятой или знаком
        равенства ломало бы разбор — то есть корректность ответа зависела
        бы от того, какие символы в нём встретились. `SlotsSpec.check_slots`
        написан ровно для этого случая.

        Спецификация с одним полем словарь тоже принимает: клиенту не
        нужно знать заранее, сколько полей у вопроса, — он шлёт то, что
        собрал с формы.
        """
        question = self.current()
        if question is None:
            return TurnResult(False, [TextBlock("Сессия уже завершена.")], None)

        check_slots = getattr(question.spec, "check_slots", None)
        if check_slots is None:
            single = next(iter(values.values()), "") if len(values) == 1 else ""
            return self.submit(single)
        return self._turn(question, check_slots(values, mode=self._mode))

    def _turn(self, question: Question, verdict: Verdict) -> TurnResult:
        """Общий хвост хода: попытки, итог, следующий вопрос."""
        self._attempts += 1

        retry_left = (not verdict.accepted
                      and self._attempts < self._max_attempts)
        if retry_left:
            # Вопрос не закрыт: итог не пишем, иначе одна попытка из
            # нескольких попала бы в статистику как отдельный результат.
            return TurnResult(
                False,
                self._feedback(question, verdict, closing=False),
                list(question.statement))

        self._outcomes.append(Outcome(
            index=self._index,
            accepted=verdict.accepted,
            attempts=self._attempts,
            mode=verdict.mode.value,
            reason=verdict.reason.value,
        ))
        feedback = self._feedback(question, verdict, closing=True)

        self._index += 1
        self._attempts = 0
        following = self.current()
        return TurnResult(
            verdict.accepted,
            feedback,
            list(following.statement) if following is not None else None)

    # ---------- Обратная связь ----------

    def _feedback(self, question: Question, verdict: Verdict,
                  *, closing: bool) -> List[Block]:
        blocks: List[Block] = [
            TextBlock("Верно." if verdict.accepted else "Неверно.")]

        if verdict.detail:
            blocks.append(TextBlock(verdict.detail))

        if verdict.slots:
            wrong = [name for name, sub in verdict.slots if not sub.accepted]
            if wrong and not verdict.accepted:
                blocks.append(TextBlock("Проверьте: " + ", ".join(wrong)))

        if not verdict.accepted and not closing:
            left = self._max_attempts - self._attempts
            blocks.append(TextBlock(f"Осталось попыток: {left}."))

        if closing and not verdict.accepted and self._reveal_answer:
            blocks.append(TextBlock("Правильный ответ:"))
            blocks.extend(question.spec.display_blocks())

        return blocks

    # ---------- Снимок ----------

    def state(self) -> dict:
        """
        Снимок сессии целиком, включая сами вопросы.

        Прогресса тут мало — важнее вопросы. `WordsSession` мог снимать
        только прогресс, потому что словарь лежит в БД и пересобирается
        детерминированно. Здесь вопрос породил генератор со случайными
        параметрами: пересборка даст ДРУГОЕ задание, и восстановление
        одного прогресса показало бы студенту не то, на что он отвечал.

        Поэтому уезжают и условие, и спецификация: обе стороны
        сериализуемы (`Block.to_dict` и `AnswerSpec.to_dict`), и это
        ровно то, ради чего спецификация делалась данными.
        """
        return {
            "questions": [q.to_dict() for q in self._questions],
            "index": self._index,
            "attempts": self._attempts,
            "outcomes": [o.to_dict() for o in self._outcomes],
            "mode": self._mode.value if self._mode is not None else None,
            "max_attempts": self._max_attempts,
            "reveal_answer": self._reveal_answer,
            "meta": dict(self.meta),
            # Сценарий уезжает целиком: по нему решается, писать ли
            # попытку. Восстанови мы сессию без него — контракт был бы
            # утрачен, и сессия «тренировки без статистики» после переезда
            # начала бы писать попытки.
            "scenario": (self._scenario.to_dict()
                         if self._scenario is not None else None),
        }

    def restore(self, state: dict) -> None:
        """
        Вернуть снимок. Вопросы ЗАМЕЩАЮТСЯ теми, что в снимке.

        Замещение, а не слияние: восстановление идёт поверх свежесобранного
        генератором задания, и оставить его вопросы значило бы подменить
        студенту условие на середине сессии.
        """
        self._questions = [Question.from_dict(q)
                           for q in state.get("questions") or []]
        self._index = int(state.get("index", 0))
        self._attempts = int(state.get("attempts", 0))
        self._outcomes = [Outcome.from_dict(o)
                          for o in state.get("outcomes") or []]
        stored_mode = state.get("mode")
        self._mode = CheckMode(stored_mode) if stored_mode else None
        self._max_attempts = max(1, int(state.get("max_attempts", 1)))
        self._reveal_answer = bool(state.get("reveal_answer", True))
        self.meta = dict(state.get("meta") or {})
        stored_scenario = state.get("scenario")
        self._scenario = (Scenario.from_dict(stored_scenario)
                          if stored_scenario else None)


# ======================================================================
#  Сборка сессии из готовых заданий
# ======================================================================

def question_from_task(task, *, widget: str = "") -> Optional[Question]:
    """
    Сделать вопрос из статического задания, если у него есть спецификация.

    None значит «это задание проверять нечем» — и это законный ответ, а не
    ошибка: большинство заданий такими и останутся.
    """
    spec = getattr(task, "answer_spec", None)
    if spec is None:
        return None
    # Число вариантов теста берётся из meta задания: генератор объявил
    # намерение показать ответ выбором, а не полем ввода. Ключ `choices`
    # кладёт финальный узел графа; словарём он бывает, когда слотов
    # несколько — тогда тестом задаётся не отдельный слот, а вопрос
    # целиком, и брать первое попавшееся число нельзя.
    raw_choices = task.meta.get("choices")
    options_count = int(raw_choices) if isinstance(raw_choices, int) else 0
    return Question(statement=list(task.statement), spec=spec,
                    widget=widget or str(task.meta.get("widget", "")),
                    options_count=options_count)


def session_from_tasks(tasks: Sequence, **kwargs) -> Optional[SpecSession]:
    """
    Собрать сессию из статических заданий, пропустив непроверяемые.

    None — если проверять нечего ни в одном. Так вызывающий отличает
    «нет интерактива» от «пустая сессия», не заглядывая внутрь.
    """
    questions = [q for q in (question_from_task(t) for t in tasks)
                 if q is not None]
    if not questions:
        return None
    meta = dict(getattr(tasks[0], "meta", {})) if tasks else {}
    return SpecSession(questions, meta=meta, **kwargs)


def session_from_task(task, **kwargs) -> Optional[SpecSession]:
    """Сессия из одного задания. None — если его нечем проверять."""
    return session_from_tasks([task], **kwargs)


__all__ = [
    "Question", "Outcome", "SpecSession",
    "question_from_task", "session_from_task", "session_from_tasks",
]
