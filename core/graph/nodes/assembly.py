"""
Узлы сборки задания.

task        — финал по умолчанию: текст условия + слоты ответа → TASK.
block_list  — аккумулятор: N входов-блоков → list[Block].
static_task — низкоуровневый финал: StaticTask(statement=..., answer=...).

Про два финала
--------------
`static_task` собирает задание из ГОТОВЫХ блоков, поэтому перед ним в
каждом графе стоит слой узлов «значение → блок» (`to_block`, `text`,
`expr_block`) и `block_list`. `task` принимает значения напрямую и
рендерит сам — этот слой из графа исчезает (план, §7.1).

Оба остаются: `static_task` нужен там, где блоки собраны нетипично
(картинка с подписью, таблица, порядок вперемешку), и сохранённые графы
продолжают работать без правок. Но начинать следует с `task`.

StaticTask из core.task — чистый dataclass (без Qt), поэтому импортируется
на верхнем уровне. Блоки внутри списков могут быть любыми объектами Block.
"""

from __future__ import annotations

import re

from core.task import StaticTask

from ..errors import GraphValidationError
from ..node import ExecContext, Node, Port
from ..port_types import PortType


class BlockListNode(Node):
    """Собрать несколько блоков в список (в порядке in0, in1, ...)."""
    type_id = "block_list"
    category = "assembly"
    display_name = "Список блоков"
    OUTPUTS = [Port("out", PortType.BLOCK_LIST)]
    PARAMS_SCHEMA = {"count": {"type": "int", "default": 1}}

    def _count(self) -> int:
        try:
            return max(1, int(self.params.get("count", 1)))
        except (TypeError, ValueError):
            raise GraphValidationError(
                f"{self.node_ref()}: 'count' должен быть целым ≥ 1."
            )

    def validate_params(self) -> None:
        self._count()

    def input_ports(self):
        return [Port(f"in{i}", PortType.BLOCK, required=False)
                for i in range(self._count())]

    def compute(self, inputs, ctx: ExecContext):
        out = []
        for i in range(self._count()):
            value = inputs.get(f"in{i}")
            if value is not None:
                out.append(value)
        return {"out": out}


class TaskNode(Node):
    """
    Финал графа: текст условия и слоты ответа — без узлов-обёрток.

    Что здесь происходит (план, §7.1)
    ---------------------------------
    Раньше финал требовал `BLOCK_LIST` на обоих входах, поэтому перед ним
    в каждом графе стоял слой преобразования «значение → блок»: `to_block`
    или `text` на условие, ещё один на ответ, `block_list` на каждый
    список. Здесь условие — параметр-текст с маркерами `#имя#` (входы
    появляются по маркерам, как у `text`), а ответ — объявленные слоты,
    в которые значения приходят типизированными.

    И это же место, где смыкаются этапы 1 и 5. Слот объявляет не только
    ЧТО показать, но и что значит «верно»: допуск, размерность, синонимы,
    отвергаемые формы. Поэтому узел выдаёт `StaticTask` с заполненной
    `answer_spec`, и задание становится проверяемым (`is_checkable`) —
    само, без отдельного «интерактивного» генератора.

    Блоки ответа при этом НЕ пишутся автором: они выводятся из
    спецификации (`AnswerSpec.display_blocks`). Это центральное решение
    §1 — «ответ становится данными, а блок для показа выводится из них» —
    в том единственном месте, где автор задания его видит.

    Параметры
    ---------
    statement       — текст условия, `#имя#` создаёт вход;
    slots           — объявления слотов ответа, по одному на строку
                      (см. `answer_slots.py`);
    layout          — раскладка ответа: `lines` (по блоку на слот),
                      `inline` (одной строкой), `template` (свой текст);
    answer_template — текст для раскладки `template`; в нём `#имя#` —
                      это и слоты, и переменные условия;
    check_mode      — режим сравнения по умолчанию для всех слотов
                      (§5.1); отдельный слот может его перекрыть.
    widget          — чем рисовать ввод; пусто значит «пусть решает
                      платформа» (см. ниже).

    Порт `blocks` (необязательный) добавляет к условию готовые блоки —
    картинку, график, матрицу. Он не делает узел «тем же самым, что и
    раньше»: обязательным он не является, и в графе, где условие — текст,
    ни одного узла-обёртки не остаётся.

    Способ ввода — тоже режим показа
    --------------------------------
    `widget` появился, когда убирали `sentence_fill`. Единственное, ради
    чего тот узел стоило бы держать, — ввод ПО МЕСТУ, полями внутри
    предложения. Но это не отдельный вид задания и даже не отдельный
    узел: проверка та же, ответ тот же, отличается только рисование.
    Ровно так же, как тест (§2) оказался режимом показа ответа, а не
    третьим типом задания.

    Поэтому здесь просто имя виджета, а список совместимых знает реестр
    (`core/widgets.py`). Несовместимое имя — ошибка при сохранении
    графа, а не молчаливая подмена: подменив, мы показали бы студенту не
    тот способ ввода, а причину спрятали бы.
    """
    type_id = "task"
    category = "assembly"
    display_name = "Задание"
    description = ("Финал графа: текст условия с #имя# и слоты ответа "
                   "(число/выражение/строка) — сразу с проверкой. "
                   "Выход: TASK.")
    OUTPUTS = [Port("out", PortType.TASK)]
    PARAMS_SCHEMA = {
        "statement": {"type": "text", "default": ""},
        "slots": {"type": "list", "default": []},
        "layout": {"type": "enum", "values": ["lines", "inline", "template"],
                   "default": "lines"},
        "answer_template": {"type": "text", "default": "", "optional": True},
        "check_mode": {"type": "enum", "values": ["soft", "strict"],
                       "default": "soft"},
        "widget": {"type": "str", "default": "", "optional": True},
        "styles": {"type": "list", "default": [], "optional": True},
    }

    # ---------- параметры ----------

    def _statement(self) -> str:
        return str(self.params.get("statement", "") or "")

    def _styles(self) -> list[str]:
        """
        Оформление абзацев условия — по строке на абзац, как `slots`.

        Отдельным параметром, а не разметкой внутри текста: `#имя#` в
        условии уже занято маркерами входов, и второй язык внутри той же
        строки означал бы, что содержание задания начинает зависеть от
        того, какие символы в него попали. Здесь оформление лежит рядом с
        текстом и на него не влияет.
        """
        raw = self.params.get("styles") or []
        if isinstance(raw, str):
            raw = raw.splitlines()
        return [str(line or "").strip().lower() for line in raw]

    def _answer_template(self) -> str:
        return str(self.params.get("answer_template", "") or "")

    def _layout(self) -> str:
        layout = str(self.params.get("layout", "lines") or "lines")
        if layout not in ("lines", "inline", "template"):
            raise GraphValidationError(
                f"{self.node_ref()}: раскладка {layout!r} неизвестна; "
                f"допустимы lines, inline, template.")
        return layout

    def _slots(self):
        from .answer_slots import parse_slots
        return parse_slots(self.params.get("slots"))

    def _widget(self) -> str:
        return str(self.params.get("widget", "") or "").strip()

    def _mode(self):
        from core.answers import CheckMode
        raw = str(self.params.get("check_mode", "soft") or "soft")
        try:
            return CheckMode(raw)
        except ValueError:
            raise GraphValidationError(
                f"{self.node_ref()}: check_mode={raw!r} — допустимы "
                f"{', '.join(m.value for m in CheckMode)}.")

    def _spec_kind(self, decls) -> str:
        """
        Каким будет вид спецификации — по одним объявлениям, до запуска.

        Знать это заранее нужно ровно для проверки виджета: несовместимую
        пару надо ловить при сохранении графа, а не при выдаче задания
        студенту. Само правило то же, по которому `compute` собирает
        ответ, и держать его надо здесь же, рядом.
        """
        if len(decls) != 1:
            return "slots"
        decl = decls[0]
        if decl.many or decl.kind == "matrix":
            return "slots"
        return {"number": "number", "expr": "expression",
                "text": "text"}[decl.kind]

    def validate_params(self) -> None:
        decls = self._slots()
        self._layout()
        self._mode()

        name = self._widget()
        if name:
            from core.widgets import registry
            widget = registry.get(name)
            if widget is None:
                known = ", ".join(sorted(w.name for w in registry.all()))
                raise GraphValidationError(
                    f"{self.node_ref()}: виджет {name!r} не зарегистрирован; "
                    f"есть {known}.")
            if decls and self._spec_kind(decls) not in widget.kinds:
                raise GraphValidationError(
                    f"{self.node_ref()}: виджет {name!r} не обслуживает "
                    f"ответ вида {self._spec_kind(decls)!r}; он умеет "
                    f"{', '.join(sorted(widget.kinds))}.")

        from .compute import _marker_names
        names = {d.name for d in decls}
        clash = names.intersection(_marker_names(self._statement()))
        if clash:
            # Совпадение имени слота с маркером условия означает, что
            # ответ печатается в самом условии. Молча соединить их в один
            # порт было бы «умно» и неверно: задание показывало бы ответ.
            raise GraphValidationError(
                f"{self.node_ref()}: {', '.join(sorted(clash))} — "
                f"одновременно слот ответа и маркер условия. Ответ попал бы "
                f"в текст условия; переименуйте одно из двух.")

    def summary(self) -> str:
        text = " ".join(self._statement().split())
        head = f"«{text}»" if text else ""
        try:
            count = len(self._slots())
        except GraphValidationError:
            return head
        if not count:
            return head
        tail = f"{count} слот." if head else f"{count} слот. ответа"
        return f"{head} {tail}".strip()

    # ---------- порты ----------

    def input_ports(self):
        from .compute import _marker_names
        decls = self._slots()
        names = {d.name for d in decls}
        ports = [Port(d.name, d.port_type) for d in decls]
        markers = _marker_names(self._statement())
        for name in _marker_names(self._answer_template()):
            if name not in markers:
                markers.append(name)
        ports += [Port(n, PortType.ANY, required=False)
                  for n in markers if n not in names]
        # Неверные варианты строкового теста приходят списком: у числа и
        # выражения их порождает сама спецификация, у строки — нет.
        ports += [Port(f"{d.name}_wrong", PortType.LIST, required=False)
                  for d in decls if d.wants_wrong_port]
        ports.append(Port("vars", PortType.NUMBER_DICT, required=False))
        # Готовые блоки условия: картинка, график, таблица. Необязателен —
        # ради него слой обёрток в графе не появляется.
        ports.append(Port("blocks", PortType.BLOCK_LIST, required=False))
        return ports

# ---------- исполнение ----------

    def compute(self, inputs, ctx: ExecContext):
        from core.answers import SlotsSpec
        from core.blocks import TextBlock
        from .compute import _fill_template

        decls = self._slots()
        mode = self._mode()
        built = [(d, d.build(inputs.get(d.name), mode,
                             inputs.get(f"{d.name}_wrong")))
                 for d in decls]

        statement: list = []
        text = _fill_template(self._statement(), inputs)
        statement.extend(_statement_blocks(text, self._styles()))
        extra = inputs.get("blocks")
        if extra:
            statement.extend(extra if isinstance(extra, list) else [extra])

        if len(built) == 1:
            # Один слот — сама спецификация, а не набор из одного. Иначе
            # ввод пришлось бы писать как «имя=значение» там, где поле одно.
            answer_spec = built[0][1]
        elif built:
            answer_spec = SlotsSpec(
                slots=tuple((d.name, spec) for d, spec in built), mode=mode)
        else:
            answer_spec = None

        meta = {"source": "graph"}
        # Способ ввода — свойство ПОКАЗА, поэтому едет в meta рядом с
        # `choices`, а не внутрь спецификации: одна и та же проверка
        # обслуживает и поле, и пропуски в тексте, и палитру формул.
        if self._widget():
            meta["widget"] = self._widget()
        # Тест — режим ПОКАЗА ответа (§2), поэтому намерение автора
        # живёт в meta задания, а не в спецификации: та же проверка
        # обслуживает и поле ввода, и выбор из вариантов.
        choices = {d.name: d.choices for d in decls if d.choices}
        if choices:
            meta["choices"] = (list(choices.values())[0] if len(built) == 1
                               else choices)

        # Варианты печатаются в условии — иначе `choices=4` даёт тест на
        # экране и открытый вопрос в .docx. Сессия их оттуда уберёт: там
        # варианты рисует виджет. Порядок один и тот же, он выводится из
        # содержимого спецификации.
        if isinstance(meta.get("choices"), int) and answer_spec is not None:
            from core.interactive import option_blocks
            statement.extend(option_blocks(answer_spec, meta["choices"]))

        return {"out": StaticTask(
            statement=statement,
            answer=self._render_answer(built, inputs),
            meta=meta,
            answer_spec=answer_spec,
        )}

    def _render_answer(self, built, inputs) -> list:
        """
        Блоки показа ответа. Выводятся из спецификаций, а не пишутся
        автором — в этом весь смысл инверсии из §1.

        Подпись слота — принадлежность ПОКАЗА, а не значения: в блоке
        ответа стоит «S = 1900 м», а принимается «1900 м», потому что
        подпись поля рисует виджет ввода. Проверять её вместе со
        значением значило бы требовать от ученика перепечатать шапку.
        """
        from core.blocks import FormulaBlock, TextBlock
        from .compute import _fill_template, _join_prefix

        layout = self._layout()

        if layout == "template":
            values = dict(inputs)
            values.update({d.name: _slot_text(spec) for d, spec in built})
            text = _fill_template(self._answer_template(), values)
            return [TextBlock(text)] if text.strip() else []

        if not built:
            return []

        # Подпись ставится там, где без неё непонятно: при нескольких слотах
        # или когда автор написал её сам. Единственный слот, названный `s`,
        # печатался бы как «s = 35 м» — это шум, а не подпись.
        def labelled(decl) -> bool:
            return len(built) > 1 or bool(decl.options.get("label"))

        if layout == "inline":
            parts = [
                _join_prefix(d.label, _slot_text(spec)) if labelled(d)
                else _slot_text(spec)
                for d, spec in built
            ]
            return [TextBlock(", ".join(parts))]

        out: list = []
        for d, spec in built:
            blocks = spec.display_blocks()
            if not labelled(d):
                out.extend(blocks)
                continue
            for index, block in enumerate(blocks):
                if index:
                    out.append(block)
                elif isinstance(block, FormulaBlock):
                    out.append(FormulaBlock(_join_prefix(d.label, block.latex)))
                else:
                    out.append(
                        TextBlock(_join_prefix(d.label, block.render_plain())))
        return out


def _slot_text(spec) -> str:
    """
    Плоское представление значения слота — для раскладок `inline` и
    `template`, где ответ собирается в одну строку.

    Формула отдаётся своим латехом без долларов: `render_plain()` вернул
    бы `$x^{2}$`, а внутри предложения это мусор. Раскладке `lines`
    ничего плоского не нужно — там формула остаётся формулой.
    """
    from core.blocks import FormulaBlock
    parts = []
    for block in spec.display_blocks():
        parts.append(block.latex if isinstance(block, FormulaBlock)
                     else block.render_plain())
    return " ".join(p for p in parts if p)


class StaticTaskNode(Node):
    """
    Низкоуровневый финал: собрать StaticTask из списков готовых блоков.

    Нужен там, где условие или ответ собраны нетипично — картинка с
    подписью, таблица, блоки вперемешку. Для обычного задания берите
    `task`: он не требует слоя узлов «значение → блок» и заодно делает
    задание проверяемым.
    """
    type_id = "static_task"
    category = "assembly"
    display_name = "Задание из блоков"
    INPUTS = [
        Port("statement", PortType.BLOCK_LIST),
        Port("answer", PortType.BLOCK_LIST),
    ]
    OUTPUTS = [Port("out", PortType.TASK)]

    def compute(self, inputs, ctx: ExecContext):
        statement = inputs.get("statement") or []
        answer = inputs.get("answer") or []
        if not isinstance(statement, list):
            statement = [statement]
        if not isinstance(answer, list):
            answer = [answer]
        return {"out": StaticTask(
            statement=list(statement),
            answer=list(answer),
            meta={"source": "graph"},
        )}


def parse_style(line: str) -> dict:
    """
    Строка оформления → аргументы TextBlock. Слова через пробел, порядок
    не важен: «крупный жирный» и «жирный крупный» — одно и то же.

    Неизвестное слово молча игнорируется, а не роняет граф: оформление —
    не смысл задания, и терять сгенерированное задание из-за опечатки в
    стиле было бы несоразмерно.
    """
    words = set((line or "").replace(",", " ").split())
    size = ("small" if words & {"мелкий", "small"}
            else "large" if words & {"крупный", "large"}
            else "normal")
    return {"size": size,
            "bold": bool(words & {"жирный", "bold"}),
            "italic": bool(words & {"курсив", "italic"})}


def _statement_blocks(text: str, styles: list) -> list:
    """
    Текст условия → абзацы, по одному блоку на абзац.

    Абзацы разделяются ПУСТОЙ строкой, а не переводом строки: перенос
    внутри абзаца — обычное дело в условии (формула с новой строки,
    перечисление), и разрывать по нему значило бы плодить блоки там, где
    автор просто отформатировал текст.

    Стилей может быть меньше, чем абзацев, — остальные обычные. Это не
    послабление, а нормальный случай: оформляют обычно один-два абзаца из
    пяти.
    """
    from core.blocks import TextBlock

    chunks = [c.strip() for c in re.split(r"\n\s*\n", text)]
    chunks = [c for c in chunks if c]
    out = []
    for index, chunk in enumerate(chunks):
        style = styles[index] if index < len(styles) else ""
        out.append(TextBlock(chunk, **parse_style(style)))
    return out
