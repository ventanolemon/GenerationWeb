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

    Порт `blocks` (необязательный) добавляет к условию готовые блоки —
    картинку, график, матрицу. Он не делает узел «тем же самым, что и
    раньше»: обязательным он не является, и в графе, где условие — текст,
    ни одного узла-обёртки не остаётся.
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
    }

    # ---------- параметры ----------

    def _statement(self) -> str:
        return str(self.params.get("statement", "") or "")

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

    def _mode(self):
        from core.answers import CheckMode
        raw = str(self.params.get("check_mode", "soft") or "soft")
        try:
            return CheckMode(raw)
        except ValueError:
            raise GraphValidationError(
                f"{self.node_ref()}: check_mode={raw!r} — допустимы "
                f"{', '.join(m.value for m in CheckMode)}.")

    def validate_params(self) -> None:
        decls = self._slots()
        self._layout()
        self._mode()

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
        built = [(d, d.build(inputs.get(d.name), mode)) for d in decls]

        statement: list = []
        text = _fill_template(self._statement(), inputs)
        if text.strip():
            statement.append(TextBlock(text))
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
        # Тест — режим ПОКАЗА ответа (§2), поэтому намерение автора
        # живёт в meta задания, а не в спецификации: та же проверка
        # обслуживает и поле ввода, и выбор из вариантов.
        choices = {d.name: d.choices for d in decls if d.choices}
        if choices:
            meta["choices"] = (list(choices.values())[0] if len(built) == 1
                               else choices)

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
