"""
Пул значений: таблица, из которой берут случайную строку.

Зачем это отдельно от словаря английского
-----------------------------------------
Английский читает словарь `words_file` (термин → перевод), русскому нужны
пары «слово с пропуском → правильное слово», информатике — просто списки
расширений и доменов. Три формата под одну и ту же нужду, и каждый новый
предмет добавлял бы четвёртый.

Здесь общая форма — **таблица**: строки и именованные столбцы. Она
покрывает все три случая, потому что словарь это таблица из двух
столбцов, а список — из одного.

Ради чего затевалось: завести генератор должно быть заполнением таблицы,
а не программированием. Автор пишет столбцы и строки прямо в узле —
файл нужен, только когда строк сотни.

Своего типа порта пул не заводит: таблица едет обычным LIST, строка —
списком значений столбцов. §7.4 плана требует не растить ядро под
предметные области, и таблица как раз не предметная.
"""

from __future__ import annotations

from ..errors import GraphValidationError, RetryGeneration
from ..node import ExecContext, Node, Port
from ..port_types import PortType


#: Разделитель столбцов в строке таблицы. Вертикальная черта, а не
#: запятая и не точка с запятой: в словах и предложениях запятые есть, а
#: черты не бывает. Экранирования нет намеренно — оно потребовало бы от
#: автора помнить правило.
SEPARATOR = "|"


def parse_columns(raw) -> list[str]:
    """Имена столбцов. Пусто — один безымянный столбец «значение»."""
    if isinstance(raw, str):
        raw = raw.split(SEPARATOR)
    names = [str(x).strip() for x in (raw or []) if str(x).strip()]
    if not names:
        return ["значение"]
    seen: set[str] = set()
    for name in names:
        if not name.isidentifier():
            raise GraphValidationError(
                f"Столбец {name!r}: имя должно быть идентификатором — оно "
                f"становится именем выходного порта, а по именам ходят "
                f"провода.")
        if name in seen:
            raise GraphValidationError(f"Столбец {name!r} объявлен дважды.")
        seen.add(name)
    return names


def parse_rows(raw, columns: list[str]) -> list[list[str]]:
    """
    Строки таблицы. Каждая — значения столбцов через `|`.

    Строка короче объявленных столбцов дополняется пустыми, длиннее —
    ошибка: лишнее значение почти наверняка означает лишнюю черту в
    тексте, и промолчать здесь — оставить автора со сдвинутыми
    столбцами.
    """
    out: list[list[str]] = []
    for index, item in enumerate(raw or [], start=1):
        if isinstance(item, (list, tuple)):
            cells = [str(c).strip() for c in item]
        else:
            text = str(item).strip()
            if not text:
                continue
            cells = [c.strip() for c in text.split(SEPARATOR)]
        if len(cells) > len(columns):
            raise GraphValidationError(
                f"Строка {index}: значений {len(cells)}, а столбцов "
                f"{len(columns)} — лишний разделитель «{SEPARATOR}»?")
        cells += [""] * (len(columns) - len(cells))
        out.append(cells)
    return out


def _read_file(path: str, columns: list[str]) -> list[list[str]]:
    """
    Таблица из файла: JSON-список или текст по строке на запись.

    Два формата, а не один, потому что источники разные: JSON приходит
    выгрузкой, а текст с чертами человек набирает руками, и требовать от
    него кавычек с квадратными скобками незачем.
    """
    import json
    from ..resources import describe, resolve

    file = resolve(path)
    if not file.exists():
        raise GraphValidationError(f"Файл пула не найден: {describe(path)}")
    text = file.read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GraphValidationError(
                f"Файл пула {describe(path)}: не разбирается как JSON "
                f"({exc.msg}).")
        if isinstance(data, dict):
            # Словарь — таблица из двух столбцов: так уже лежат словари
            # английского, и переделывать их ради пула не нужно.
            data = [[k, v] for k, v in data.items()]
        if not isinstance(data, list):
            raise GraphValidationError(
                f"Файл пула {path!r}: ожидался список строк или словарь.")
        return parse_rows(data, columns)
    return parse_rows(text.splitlines(), columns)


class PoolNode(Node):
    """
    Таблица значений — источник. Строки прямо в узле или из файла.

    Встроенная таблица главнее файла: файл выбирают, когда строк сотни, а
    десяток автор наберёт здесь же и увидит их вместе с графом.
    """
    type_id = "pool"
    category = "source"
    display_name = "Пул значений"
    description = ("Таблица значений (строки со столбцами через «|»): "
                   "встроенная или из файла. Источник. Выход: LIST.")
    OUTPUTS = [Port("out", PortType.LIST)]
    PARAMS_SCHEMA = {
        "columns": {"type": "list", "default": []},
        "rows": {"type": "list", "default": []},
        "file": {"type": "file", "default": "", "optional": True,
                 "resource": "pools",
                 "filter": "Таблица (*.json *.txt *.csv)"},
    }

    def _columns(self) -> list[str]:
        return parse_columns(self.params.get("columns"))

    def validate_params(self) -> None:
        columns = self._columns()
        parse_rows(self.params.get("rows"), columns)
        if not self.params.get("rows") and not str(
                self.params.get("file", "")).strip():
            raise GraphValidationError(
                f"{self.node_ref()}: заполните таблицу или укажите файл.")

    def summary(self) -> str:
        rows = self.params.get("rows") or []
        return f"{len(rows)} стр." if rows else "из файла"

    def compute(self, inputs, ctx: ExecContext):
        columns = self._columns()
        rows = parse_rows(self.params.get("rows"), columns)
        if not rows:
            rows = _read_file(str(self.params.get("file", "")).strip(),
                              columns)
        if not rows:
            raise RetryGeneration(f"{self.node_ref()}: таблица пуста.")
        return {"out": rows}


class PoolPickNode(Node):
    """
    Взять из таблицы случайную строку — по выходу на столбец.

    Столбцы объявляются здесь же, а не берутся у источника: между ними
    провод, а по проводу едут значения, не схема. Дублирование мелкое, и
    зато узел читается сам по себе — видно, что откуда берётся.

    `прочие` — значения того же столбца из ДРУГИХ строк. Нужны тесту:
    неверные варианты для «переведите слово» это другие переводы, и
    выдумать их нельзя, они в таблице.
    """
    type_id = "pool_pick"
    category = "source"
    display_name = "Строка из пула"
    description = ("Случайная строка таблицы: по выходу на столбец плюс "
                   "чужие значения для теста. Вход: LIST.")
    INPUTS = [Port("in", PortType.LIST)]
    PARAMS_SCHEMA = {
        "columns": {"type": "list", "default": []},
        "others": {"type": "int", "default": 0, "optional": True},
        "others_from": {"type": "string", "default": "", "optional": True},
    }

    def _columns(self) -> list[str]:
        return parse_columns(self.params.get("columns"))

    def _others_count(self) -> int:
        try:
            count = int(self.params.get("others", 0) or 0)
        except (TypeError, ValueError):
            raise GraphValidationError(
                f"{self.node_ref()}: 'others' должно быть целым ≥ 0.")
        if count < 0:
            raise GraphValidationError(
                f"{self.node_ref()}: 'others' не может быть отрицательным.")
        return count

    def _others_column(self, columns: list[str]) -> str:
        name = str(self.params.get("others_from", "") or "").strip()
        if not name:
            # Последний столбец: в таблице «вопрос | ответ» неверные
            # варианты берут из ответов, и это самый частый случай.
            return columns[-1]
        if name not in columns:
            raise GraphValidationError(
                f"{self.node_ref()}: столбца {name!r} нет; "
                f"есть {', '.join(columns)}.")
        return name

    def validate_params(self) -> None:
        self._others_column(self._columns())
        self._others_count()

    def output_ports(self):
        ports = [Port(name, PortType.STRING) for name in self._columns()]
        if self._others_count():
            ports.append(Port("прочие", PortType.LIST))
        return ports

    def compute(self, inputs, ctx: ExecContext):
        columns = self._columns()
        rows = inputs.get("in") or []
        if not isinstance(rows, (list, tuple)) or not rows:
            raise RetryGeneration(
                f"{self.node_ref()}: на вход не пришла непустая таблица.")

        rows = [list(r) if isinstance(r, (list, tuple)) else [str(r)]
                for r in rows]
        narrow = [r for r in rows if len(r) < len(columns)]
        if narrow:
            raise GraphValidationError(
                f"{self.node_ref()}: в таблице строка из {len(narrow[0])} "
                f"значений, а объявлено столбцов {len(columns)}.")

        row = ctx.rng.choice(rows)
        out = {name: str(row[i]) for i, name in enumerate(columns)}

        count = self._others_count()
        if count:
            index = columns.index(self._others_column(columns))
            mine = str(row[index])
            pool = [str(r[index]) for r in rows if str(r[index]) != mine]
            out["прочие"] = (ctx.rng.sample(pool, min(count, len(pool)))
                             if pool else [])
        return out


__all__ = ["PoolNode", "PoolPickNode", "parse_columns", "parse_rows",
           "SEPARATOR"]
