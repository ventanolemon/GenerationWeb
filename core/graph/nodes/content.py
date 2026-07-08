"""
Узлы-блоки контента — обёртки над core.blocks. Каждый принимает данные и
возвращает объект Block. Никакой новой логики рендеринга.

Импорт классов блоков — ленивый, внутри compute(): они тянут PyQt6, а движок
графа в остальном headless (нужен для тестов и будущего безоконного исполнения).
"""

from __future__ import annotations

from ..errors import RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType


# Окружения LaTeX для матриц (как в matrix_block) — для стиля рендера матрицы.
_MATRIX_ENVS = ("pmatrix", "bmatrix", "vmatrix", "Vmatrix")


class ToBlockNode(Node):
    """
    Полиморфный рендер значения в блок задания (ANY → BLOCK).

    Принимает значение ЛЮБОГО типа и оборачивает его в подходящий Block,
    диспетчеризуя по фактическому типу значения в рантайме:
      * Block            → как есть (passthrough — удобно «протащить» блок);
      * IMAGE (PIL)      → ImageBlock (подпись — параметр caption);
      * MATRIX (sympy)   → FormulaBlock (как matrix_block, окружение env);
      * EXPR (sympy)     → FormulaBlock (как expr_block);
      * число/bool/строка→ TextBlock (число при style=formula — формульный блок).
    Параметр prefix добавляет 'prefix = …' к формульным блокам (и 'prefix …'
    к текстовым). Заменяет четыре узла text_block/expr_block/matrix_block/
    image_block одним и закрывает дыру «число → текстовый блок».
    """
    type_id = "to_block"
    category = "content"
    display_name = "Блок (любой тип)"
    description = ("Универсальный рендер значения в блок: число/строка/формула/"
                   "матрица/картинка/блок → BLOCK. Вход: любой тип. Выход: BLOCK.")
    INPUTS = [Port("in", PortType.ANY)]
    OUTPUTS = [Port("out", PortType.BLOCK)]
    PARAMS_SCHEMA = {
        "style": {"type": "enum", "values": ["auto", "text", "formula"],
                  "default": "auto"},
        "prefix": {"type": "string", "default": "", "optional": True},
        "relation": {"type": "string", "default": "=", "optional": True},
        "env": {"type": "enum", "values": list(_MATRIX_ENVS),
                "default": "pmatrix", "optional": True},
        "caption": {"type": "string", "default": "", "optional": True},
    }

    @staticmethod
    def _module_root(value) -> str:
        return type(value).__module__.split(".")[0]

    def _formula(self, latex: str):
        from core.blocks import FormulaBlock
        from .compute import _join_prefix
        return FormulaBlock(_join_prefix(self.params.get("prefix", ""), latex,
                                         self.params.get("relation", "=")))

    def _text(self, text: str):
        from core.blocks import TextBlock
        from .compute import _join_prefix
        # Связка '=' добавляется только при наличии префикса; для прозы задайте
        # relation='' (или префикс с двоеточием — дедуп не продублирует).
        return TextBlock(_join_prefix(self.params.get("prefix", ""), text,
                                      self.params.get("relation", "=")))

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import Block, ImageBlock
        value = inputs.get("in")
        if value is None:
            raise RetryGeneration(
                f"to_block {self.node_id!r}: на вход не пришло значение."
            )
        style = str(self.params.get("style", "auto"))

        # 1. Уже блок — отдать как есть.
        if isinstance(value, Block):
            return {"out": value}

        # 2. Картинка (PIL) — без жёсткого импорта PIL: по модулю класса.
        if self._module_root(value) == "PIL":
            return {"out": ImageBlock(value, caption=str(self.params.get("caption", "")))}

        # 3. Символьное (sympy): матрица → сетка, иначе формула.
        if self._module_root(value) == "sympy":
            from ..symbolic import is_matrix, sympy, to_latex
            if is_matrix(value):
                env = self.params.get("env", "pmatrix")
                return {"out": self._formula(
                    sympy().latex(value, mat_delim="", mat_str=env))}
            return {"out": self._formula(to_latex(value))}

        # 4. bool раньше int (bool — подкласс int).
        if isinstance(value, bool):
            return {"out": self._text("да" if value else "нет")}

        # 5. Число: по умолчанию текст, при style=formula — формула.
        if isinstance(value, (int, float)):
            if style == "formula":
                from ..symbolic import as_expr, to_latex
                return {"out": self._formula(to_latex(as_expr(value)))}
            from .compute import _format_value
            return {"out": self._text(_format_value(value))}

        # 6. Строка (и всё прочее как строка): текст или формула по style.
        text = str(value)
        if style == "formula":
            return {"out": self._formula(text)}
        return {"out": self._text(text)}


class TextBlockNode(Node):
    """Текстовый блок из строки."""
    type_id = "text_block"
    category = "content"
    display_name = "Текстовый блок"
    INPUTS = [Port("text", PortType.STRING)]
    OUTPUTS = [Port("out", PortType.BLOCK)]

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import TextBlock          # ленивый: тянет Qt
        return {"out": TextBlock(str(inputs.get("text", "")))}


class TextNode(Node):
    """
    Текстовый блок с подстановкой #имя# прямо из параметра. Объединяет шаблон,
    подстановку и обёртку в блок — для типового «текст с числами» достаточно
    ОДНОГО узла. Входы-числа создаются по маркерам #имя# в тексте; запасной
    вход vars (NUMBER_DICT) тоже принимается. Текст без маркеров — просто текст.
    """
    type_id = "text"
    category = "content"
    display_name = "Текст"
    description = ("Текстовый блок с подстановкой #имя# (числа на входах). "
                   "Один узел вместо шаблон+блок. Выход: BLOCK.")
    OUTPUTS = [Port("out", PortType.BLOCK)]
    PARAMS_SCHEMA = {"text": {"type": "text", "default": ""}}

    def input_ports(self):
        from .compute import _marker_names
        # Маркеры #имя# — полиморфные входы (ANY): число, строка, выражение.
        ports = [Port(n, PortType.ANY, required=False)
                 for n in _marker_names(self.params.get("text", ""))]
        ports.append(Port("vars", PortType.NUMBER_DICT, required=False))
        return ports

    def compute(self, inputs, ctx: ExecContext):
        from core.blocks import TextBlock          # ленивый: тянет Qt
        from .compute import _fill_template
        return {"out": TextBlock(_fill_template(self.params.get("text", ""), inputs))}
